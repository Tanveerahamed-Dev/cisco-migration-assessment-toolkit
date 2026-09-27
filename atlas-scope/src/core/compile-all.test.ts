// @vitest-environment node
/**
 * compile-all.test.ts — ONE command compiles all four files from ONE read of ONE snapshot, and either
 * the whole set lands or none of it does.
 *
 * WHAT WAS WRONG (discovery "compiler-any-snapshot" §3h). `npm run compile:data` ran only
 * compile-snapshot.mjs, so a routine recompile left the three sidecars bound to the OLD snapshot —
 * which `sameSourceBinding` then refused, silently turning every ACL binding, routing-completeness
 * answer and emission flag into "unknown" with no build error. And when the main compile threw, the
 * three sidecar compilers still wrote files bound to the NEW digest: a mixed set, either way. The
 * source path was fixed, so a second snapshot could not be compiled at all without editing the tool,
 * and a model compiled from it would have named the SAMPLE as its source.
 *
 * WHAT THIS PINS:
 *   - compile-all writes the four tracked files byte-identical to the shipped ones (sandboxed);
 *   - an injected failure at ANY point — the compile, or midway through the renames — leaves the
 *     previous set byte-identical and no staging directory behind;
 *   - a non-sample source never reaches the tracked files: its output defaults to the git-ignored
 *     `.local-data/`, and `--out` inside `src/` is refused before anything is written;
 *   - `meta.source` is repository-relative for a repository file, a bare name for an external one,
 *     and never an absolute path;
 *   - the repository's golden snapshot — a second REAL producer output — compiles end to end, names
 *     itself, and all four outputs share one binding (R6);
 *   - (verifier S1-V2/V4) --out is refused wherever it would land in a tracked or bundled location —
 *     src/ under every spelling that reaches it ("src/..data", "src./data", another case), and, for a
 *     non-sample source, ANY directory of the repository Git does not ignore — before anything is written;
 *   - (S1-V3) a per-file command refuses to leave its file bound to a different snapshot from the
 *     compiled files beside it;
 *   - (S1-V5) a rollback that cannot complete keeps the previous files and names where they are;
 *   - (S1-V9) "repository-file" means a file GIT TRACKS; an untracked file inside the repository is an
 *     external file, bound to its bytes as read.
 *
 * THE BASE of every compile here other than R6 is the golden with the per-finding evidence contract
 * removed (`baseBytes()` below) — see the comment there for why.
 */
import { execFileSync, spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import { cpSync, existsSync, mkdirSync, mkdtempSync, readdirSync, readFileSync, rmSync, statSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { afterAll, describe, expect, it } from "vitest";

import { compileToDisk } from "../../tools/lib/compile-io.mjs";
import { CompileError, OUTPUTS } from "../../tools/lib/compile-model.mjs";
import { SOURCE_BINDING_KEYS } from "./types";

const PKG = resolve(dirname(fileURLToPath(import.meta.url)), "..", "..");
const REPO = resolve(PKG, "..");
const TOOLS = resolve(PKG, "tools");
const SAMPLE_REL = "webapp/sample_data/sample_fleet.snapshot.json";
const GOLDEN = resolve(REPO, "tests", "golden", "snapshot.json");

/**
 * The bytes every compile in this file other than R6 is built on: the repository's golden snapshot (a
 * real producer output) with the per-finding evidence contract — `evidence_basis`, `evidence_refs`,
 * `evidence_refs_total` — removed from every punch-list row. That is the row shape every producer before
 * the contract wrote, and the compiler reads the absence as "not emitted" (null).
 *
 * WHY NOT THE GOLDEN AS PUBLISHED (verifier S1-V1). The golden is a stripped derivative:
 * tests/test_pipeline_golden.py `_run_pipeline` pops the date-relative sections (device_dossiers among
 * them) before freezing it, and the engine's refs legitimately point into those sections — so the golden
 * as published does not resolve its own pointers, and every case built on it turned red when the engine
 * lane regenerated it. A positive control for placement, labelling or atomicity must not fail because of
 * an unrelated producer change. The golden AS PUBLISHED is compiled explicitly, once, in R6 below.
 */
const baseBytes = (): Buffer => {
  const s = JSON.parse(readFileSync(GOLDEN, "utf8")) as { punchlist: Record<string, unknown>[] };
  s.punchlist = s.punchlist.map((row) =>
    Object.fromEntries(Object.entries(row).filter(([k]) => k !== "evidence_basis" && k !== "evidence_refs" && k !== "evidence_refs_total")),
  );
  return Buffer.from(JSON.stringify(s, null, 2), "utf8");
};
const sha256 = (b: Uint8Array): string => createHash("sha256").update(b).digest("hex");

const sandboxes: string[] = [];
afterAll(() => {
  for (const d of sandboxes) rmSync(d, { recursive: true, force: true });
});
const tmp = (prefix: string): string => {
  const d = mkdtempSync(join(tmpdir(), prefix));
  sandboxes.push(d);
  return d;
};

/** A copy of the package's tools and src skeleton, with the sample where the tools resolve it. */
function sandbox(opts: { withShipped?: boolean } = {}): { root: string; pkg: string; tools: string } {
  const root = tmp("atlas-compile-all-");
  const pkg = join(root, "atlas-scope");
  cpSync(TOOLS, join(pkg, "tools"), { recursive: true });
  const mirror = (from: string, to: string): void => {
    mkdirSync(to, { recursive: true });
    for (const n of readdirSync(from)) if (statSync(join(from, n)).isDirectory()) mirror(join(from, n), join(to, n));
  };
  mirror(resolve(PKG, "src"), join(pkg, "src"));
  mkdirSync(join(root, "webapp", "sample_data"), { recursive: true });
  writeFileSync(join(root, SAMPLE_REL), readFileSync(resolve(REPO, SAMPLE_REL)));
  if (opts.withShipped) for (const o of OUTPUTS) cpSync(resolve(PKG, o.trackedPath), join(pkg, o.trackedPath));
  return { root, pkg, tools: join(pkg, "tools") };
}

const snapshotOf = (pkg: string): Map<string, string> => {
  const m = new Map<string, string>();
  for (const o of OUTPUTS) {
    const p = join(pkg, o.trackedPath);
    m.set(o.trackedPath, existsSync(p) ? readFileSync(p, "latin1") : "<absent>");
  }
  return m;
};

const cli = (tools: string, args: string[]) =>
  spawnSync(process.execPath, [join(tools, "compile-all.mjs"), ...args], { encoding: "utf8" });

describe("one command, the whole set", () => {
  it("`npm run compile:data` runs compile-all", () => {
    const pkgJson = JSON.parse(readFileSync(resolve(PKG, "package.json"), "utf8")) as { scripts: Record<string, string> };
    expect(pkgJson.scripts["compile:data"]).toBe("node tools/compile-all.mjs");
  });

  it("the default run writes all four tracked files, byte-identical to the shipped ones", () => {
    const { pkg, tools } = sandbox();
    const r = cli(tools, []);
    expect(r.status, r.stderr).toBe(0);
    for (const o of OUTPUTS) {
      expect(readFileSync(join(pkg, o.trackedPath)).equals(readFileSync(resolve(PKG, o.trackedPath))), o.trackedPath).toBe(true);
    }
    expect(existsSync(join(pkg, ".local-data")) ? readdirSync(join(pkg, ".local-data")) : [], "no staging left behind").toEqual([]);
  });
});

describe("either the whole set lands or none of it does", () => {
  it("a failure midway through the renames rolls every file back", () => {
    const { root, pkg, tools } = sandbox({ withShipped: true });
    // Change the source so a completed run WOULD change all four files — otherwise rollback is vacuous.
    const src = join(root, SAMPLE_REL);
    const s = JSON.parse(readFileSync(src, "utf8")) as { script_version: string };
    s.script_version = "V0.0.0-atomicity";
    writeFileSync(src, JSON.stringify(s));
    const before = snapshotOf(pkg);
    let steps = 0;
    expect(() =>
      compileToDisk({
        toolsDir: tools,
        hooks: {
          beforeCommitStep: (i) => {
            steps = i;
            if (i === 2) throw new Error("injected failure after two of four renames");
          },
        },
      }),
    ).toThrow(/injected failure/);
    expect(steps, "the failure really was injected midway").toBe(2);
    expect(snapshotOf(pkg)).toEqual(before);
    expect(readdirSync(join(pkg, ".local-data")), "no staging left behind").toEqual([]);
    // Positive control: the same run without the injection DOES change the set.
    compileToDisk({ toolsDir: tools });
    const after = snapshotOf(pkg);
    for (const o of OUTPUTS) expect(after.get(o.trackedPath), o.trackedPath).not.toBe(before.get(o.trackedPath));
  });

  it("a failing compile changes no file — not even the sidecars, which used to be written anyway", () => {
    const { root, pkg, tools } = sandbox({ withShipped: true });
    const src = join(root, SAMPLE_REL);
    const s = JSON.parse(readFileSync(src, "utf8")) as { punchlist: Record<string, unknown>[] };
    s.punchlist[0] = { ...s.punchlist[0], a_field_no_compiler_knows: true };
    writeFileSync(src, JSON.stringify(s));
    const before = snapshotOf(pkg);
    let code = "";
    try {
      compileToDisk({ toolsDir: tools });
    } catch (e) {
      code = e instanceof CompileError ? e.code : String(e);
    }
    expect(code).toBe("E_UNKNOWN_PRODUCER_FIELD");
    expect(snapshotOf(pkg)).toEqual(before);
    const r = cli(tools, []);
    expect(r.status).toBe(1);
    expect(r.stderr).toMatch(/E_UNKNOWN_PRODUCER_FIELD/);
    expect(snapshotOf(pkg)).toEqual(before);
  });

  it("a per-file wrapper compiles and validates the whole set but writes only its own file", () => {
    const { pkg, tools } = sandbox();
    execFileSync(process.execPath, [join(tools, "compile-acl-bindings.mjs")], { stdio: "pipe" });
    const written = OUTPUTS.filter((o) => existsSync(join(pkg, o.trackedPath))).map((o) => o.key);
    expect(written).toEqual(["aclBindings"]);
  });

  it("a per-file command refuses to leave its file bound to a different snapshot from its siblings (S1-V3)", () => {
    /* Measured by the verifier: after the sample changed, `node tools/compile-snapshot.mjs` exited 0 and
       left the three sidecars on the OLD digest — which sameSourceBinding then refuses silently, turning
       every ACL binding, RIB answer and emission flag into "unknown". */
    const { root, pkg, tools } = sandbox({ withShipped: true });
    const src = join(root, SAMPLE_REL);
    const s = JSON.parse(readFileSync(src, "utf8")) as { script_version: string };
    s.script_version = "V0.0.0-mixed-set";
    writeFileSync(src, JSON.stringify(s));
    const before = snapshotOf(pkg);
    for (const name of ["compile-snapshot.mjs", "compile-acl-bindings.mjs", "compile-rib-evidence.mjs", "compile-producer-emission.mjs"]) {
      const r = spawnSync(process.execPath, [join(tools, name)], { encoding: "utf8" });
      expect(r.status, `${name}: ${r.stderr}`).toBe(2);
      expect(r.stderr, name).toMatch(/E_MIXED_SET/);
      expect(r.stderr, name).toMatch(/compile:data/);
      expect(snapshotOf(pkg), `${name} changed a file`).toEqual(before);
    }
    // The set command rebuilds all four; after it a per-file command is consistent again (exit 0).
    expect(cli(tools, []).status).toBe(0);
    const r = spawnSync(process.execPath, [join(tools, "compile-snapshot.mjs")], { encoding: "utf8" });
    expect(r.status, r.stderr).toBe(0);
  });

  it("a per-file command beside the unchanged shipped set rewrites its file byte-identically (positive control)", () => {
    const { pkg, tools } = sandbox({ withShipped: true });
    const before = snapshotOf(pkg);
    const r = spawnSync(process.execPath, [join(tools, "compile-rib-evidence.mjs")], { encoding: "utf8" });
    expect(r.status, r.stderr).toBe(0);
    expect(snapshotOf(pkg)).toEqual(before);
  });

  it("a rollback that cannot complete keeps the previous file and names where it is (S1-V5)", () => {
    const { root, pkg, tools } = sandbox({ withShipped: true });
    const src = join(root, SAMPLE_REL);
    const s = JSON.parse(readFileSync(src, "utf8")) as { script_version: string };
    s.script_version = "V0.0.0-rollback";
    writeFileSync(src, JSON.stringify(s));
    const before = snapshotOf(pkg);
    let err: unknown;
    try {
      compileToDisk({
        toolsDir: tools,
        hooks: {
          beforeCommitStep: (i) => {
            if (i === 2) throw new Error("injected failure after two of four renames");
          },
          // A Windows file lock on the destination: the restore of the FIRST file cannot happen.
          beforeRestoreStep: (_i, key) => {
            if (key === "fabric") throw new Error("injected lock on the restore of fabric.json");
          },
        },
      });
    } catch (e) {
      err = e;
    }
    expect(err).toBeInstanceOf(CompileError);
    expect((err as CompileError).code).toBe("E_ROLLBACK_INCOMPLETE");
    // The previous fabric.json was NOT deleted with the staging directory: it is still on disk, named.
    const staging = readdirSync(join(pkg, ".local-data")).filter((n) => n.startsWith(".compile-staging-"));
    expect(staging.length, "the staging directory holding the previous file is kept").toBe(1);
    expect(readFileSync(join(pkg, ".local-data", staging[0]!, "fabric.prev"), "latin1")).toBe(before.get("src/data/fabric.json"));
    expect((err as CompileError).message).toContain(staging[0]!);
    // Every file whose restore DID succeed is back exactly as it was.
    const after = snapshotOf(pkg);
    for (const o of OUTPUTS.filter((x) => x.key !== "fabric")) expect(after.get(o.trackedPath), o.trackedPath).toBe(before.get(o.trackedPath));
  });
});

describe("client data never reaches the tracked files", () => {
  const external = (): { dir: string; file: string } => {
    const dir = tmp("atlas-external-");
    const file = join(dir, "client.snapshot.json");
    writeFileSync(file, baseBytes());
    return { dir, file };
  };

  it("an external source defaults its output to the git-ignored .local-data/, named by basename", () => {
    const { pkg, tools } = sandbox();
    const { dir, file } = external();
    const r = cli(tools, ["--source", file]);
    expect(r.status, r.stderr).toBe(0);
    for (const o of OUTPUTS) expect(existsSync(join(pkg, o.trackedPath)), `${o.trackedPath} must not be written`).toBe(false);
    const fabric = JSON.parse(readFileSync(join(pkg, ".local-data", "fabric.json"), "utf8")) as { meta: Record<string, unknown> };
    expect(fabric.meta.source).toBe("client.snapshot.json");
    expect(fabric.meta.sourceOrigin).toBe("external-file");
    // No absolute path anywhere in any output — the home directory's username is a privacy marker.
    for (const o of OUTPUTS) {
      const text = readFileSync(join(pkg, ".local-data", o.file), "utf8");
      expect(text.includes(dir), o.file).toBe(false);
      expect(text.includes(dir.split("\\").join("/")), o.file).toBe(false);
      expect(/"[A-Za-z]:[\\/]/.test(text), `${o.file} carries a drive-letter path`).toBe(false);
    }
  });

  it("--label names an external source; a label that is a path is refused", () => {
    const { pkg, tools } = sandbox();
    const { file } = external();
    expect(cli(tools, ["--source", file, "--label", "site-a.snapshot.json"]).status).toBe(0);
    const meta = (JSON.parse(readFileSync(join(pkg, ".local-data", "fabric.json"), "utf8")) as { meta: Record<string, unknown> }).meta;
    expect(meta.source).toBe("site-a.snapshot.json");
    const bad = cli(tools, ["--source", file, "--label", "C:\\cases\\site-a.json"]);
    expect(bad.status).toBe(2);
    expect(bad.stderr).toMatch(/E_SOURCE_LABEL/);
  });

  it.each([
    ["src"],
    ["src/data"],
    ["src/forwarding/../panels"],
    // S1-V2: a child of src/ whose NAME begins with ".." is inside src/ (path.relative says "..data").
    ["src/..data"],
    // S1-V2: Win32 drops a trailing dot or space, so "src./data" can reach src/data there.
    ["src./data"],
    ["src /data"],
    // A different case reaches the same directory on a case-insensitive file system.
    ["SRC/data"],
  ])("refuses --out %s for a non-sample source, writing nothing", (out) => {
    const { pkg, tools } = sandbox({ withShipped: true });
    const before = snapshotOf(pkg);
    const srcBefore = readdirSync(join(pkg, "src")).sort();
    const { file } = external();
    const r = cli(tools, ["--source", file, "--out", join(pkg, out)]);
    expect(r.status, r.stderr).toBe(2);
    expect(r.stderr).toMatch(/E_OUT_REFUSED/);
    expect(snapshotOf(pkg)).toEqual(before);
    expect(readdirSync(join(pkg, "src", "data")).sort()).toEqual(["fabric.json"]);
    expect(readdirSync(join(pkg, "src")).sort(), "nothing new was created under src/").toEqual(srcBefore);
  });

  it.each([["src/..data"], ["src./data"], ["src /data"], ["SRC/data"], ["src/panels"]])(
    "refuses --out %s even for the SAMPLE — the src/ rule alone, with no repository rule behind it (S1-V2)",
    (out) => {
      /* For a non-sample source the repository rule (S1-V4) would refuse these as well, so the cases above
         cannot tell whether the src/ containment itself is right. The sample is exempt from that rule, so
         here the src/ check is the only thing standing between --out and the tracked directory. */
      const { pkg, tools } = sandbox({ withShipped: true });
      const before = snapshotOf(pkg);
      const srcBefore = readdirSync(join(pkg, "src")).sort();
      const dataBefore = readdirSync(join(pkg, "src", "data")).sort();
      const r = cli(tools, ["--out", join(pkg, out)]);
      expect(r.status, r.stderr).toBe(2);
      expect(r.stderr).toMatch(/E_OUT_REFUSED/);
      expect(snapshotOf(pkg)).toEqual(before);
      expect(readdirSync(join(pkg, "src")).sort(), "nothing new was created under src/").toEqual(srcBefore);
      expect(readdirSync(join(pkg, "src", "data")).sort(), "no staging directory was left in src/data").toEqual(dataBefore);
    },
  );

  it("the sample may be compiled to a directory elsewhere in the repository (it is already public)", () => {
    const { pkg, tools } = sandbox();
    const r = cli(tools, ["--out", join(pkg, "review", "sample-out")]);
    expect(r.status, r.stderr).toBe(0);
    expect(existsSync(join(pkg, "review", "sample-out", "fabric.json"))).toBe(true);
  });

  it.each([["public"], ["."], ["review/out"], ["../docs/compiled"]])(
    "refuses --out %s (a repository directory Git does not ignore) for a non-sample source (S1-V4)",
    (out) => {
      /* The class is "a location Git would track or Vite would bundle", not the one directory src/. In a
         tree Git does not own (this sandbox) only .local-data/ is known to be ignored. */
      const { pkg, tools } = sandbox({ withShipped: true });
      const before = snapshotOf(pkg);
      const { file } = external();
      const r = cli(tools, ["--source", file, "--out", join(pkg, out)]);
      expect(r.status, r.stderr).toBe(2);
      expect(r.stderr).toMatch(/E_OUT_REFUSED/);
      expect(existsSync(join(pkg, out, "fabric.json"))).toBe(false);
      expect(snapshotOf(pkg)).toEqual(before);
    },
  );

  it("accepts --out inside .local-data/ and outside the repository (positive controls)", () => {
    const { pkg, tools } = sandbox();
    const { file } = external();
    const a = cli(tools, ["--source", file, "--out", join(pkg, ".local-data", "site-a")]);
    expect(a.status, a.stderr).toBe(0);
    expect(existsSync(join(pkg, ".local-data", "site-a", "fabric.json"))).toBe(true);
    const outside = tmp("atlas-outside-");
    const b = cli(tools, ["--source", file, "--out", outside]);
    expect(b.status, b.stderr).toBe(0);
    expect(existsSync(join(outside, "fabric.json"))).toBe(true);
  });

  it("in the real repository, a Git-ignored directory is accepted and a tracked one refused (S1-V4)", () => {
    const { file } = external();
    const ignored = join(PKG, "review", "_scratch", `s1-compile-probe-${process.pid}`);
    try {
      const ok = cli(TOOLS, ["--source", file, "--out", ignored]);
      expect(ok.status, ok.stderr).toBe(0);
      expect(existsSync(join(ignored, "fabric.json"))).toBe(true);
    } finally {
      rmSync(ignored, { recursive: true, force: true });
    }
    const tracked = join(PKG, "docs", `s1-compile-probe-${process.pid}`);
    try {
      const no = cli(TOOLS, ["--source", file, "--out", tracked]);
      expect(no.status, no.stderr).toBe(2);
      expect(no.stderr).toMatch(/E_OUT_REFUSED/);
      expect(existsSync(tracked)).toBe(false);
    } finally {
      // A regression (or a mutation check) that DOES write there must not leave client-shaped data in docs/.
      rmSync(tracked, { recursive: true, force: true });
    }
  });

  it("a non-sample REPOSITORY file (the golden) is also kept out of src/ by default", () => {
    const { root, pkg, tools } = sandbox();
    mkdirSync(join(root, "tests", "golden"), { recursive: true });
    writeFileSync(join(root, "tests", "golden", "snapshot.json"), baseBytes());
    expect(cli(tools, ["--source", join(root, "tests", "golden", "snapshot.json")]).status).toBe(0);
    for (const o of OUTPUTS) expect(existsSync(join(pkg, o.trackedPath))).toBe(false);
    expect(existsSync(join(pkg, ".local-data", "fabric.json"))).toBe(true);
  });

  it("an UNTRACKED file inside the repository is an external file, bound to its bytes as read (S1-V9)", () => {
    /* Before: origin was decided by path, so this file was "repository-file" and its "exact" digest was
       taken over the LF form — matching neither its bytes on disk nor any object Git holds. */
    const dir = join(PKG, ".local-data", `s1-untracked-${process.pid}`);
    const out = tmp("atlas-untracked-out-");
    const crlf = Buffer.from(baseBytes().toString("latin1").split("\n").join("\r\n"), "latin1");
    try {
      mkdirSync(dir, { recursive: true });
      writeFileSync(join(dir, "crlf.snapshot.json"), crlf);
      const r = cli(TOOLS, ["--source", join(dir, "crlf.snapshot.json"), "--out", out]);
      expect(r.status, r.stderr).toBe(0);
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
    const meta = (JSON.parse(readFileSync(join(out, "fabric.json"), "utf8")) as { meta: Record<string, unknown> }).meta;
    expect(meta.sourceOrigin).toBe("external-file");
    expect(meta.source).toBe("crlf.snapshot.json");
    expect(meta.sourceExactSha256).toBe(`sha256:${sha256(crlf)}`);
    expect(meta.sourceExactSha256).not.toBe(`sha256:${String(meta.sourceSha256)}`);
  });

  it("a TRACKED file is a repository file, named by its repository path (control for the above)", () => {
    const out = tmp("atlas-tracked-out-");
    const r = cli(TOOLS, ["--source", resolve(REPO, SAMPLE_REL), "--out", out]);
    expect(r.status, r.stderr).toBe(0);
    const meta = (JSON.parse(readFileSync(join(out, "fabric.json"), "utf8")) as { meta: Record<string, unknown> }).meta;
    expect(meta.sourceOrigin).toBe("repository-file");
    expect(meta.source).toBe(SAMPLE_REL);
  });

  it("the package's .gitignore ignores .local-data/", () => {
    const r = spawnSync("git", ["check-ignore", "-q", ".local-data/fabric.json"], { cwd: PKG });
    expect(r.status, "git check-ignore exit status (0 = ignored)").toBe(0);
  });

  it("a missing source, an unknown flag and a flag with no value are refused with a code", () => {
    const { tools } = sandbox();
    const missing = cli(tools, ["--source", join(tmpdir(), "no-such-atlas-snapshot.json")]);
    expect(missing.status).toBe(1);
    expect(missing.stderr).toMatch(/E_SOURCE_MISSING/);
    expect(cli(tools, ["--frobnicate"]).status).toBe(2);
    expect(cli(tools, ["--source"]).status).toBe(2);
  });
});

/* R6 — the golden AS PUBLISHED, with no transform. If this block is red with E_EVIDENCE_REF_UNRESOLVED on
   refs into a section the golden does not carry (device_dossiers), the golden is a stripped derivative that
   cannot back its own citations: an owner decision between this compiler and the engine lane (verifier
   S1-V1), never a reason to loosen pointer resolution. */
describe("R6: the repository's golden snapshot compiles end to end (a second real producer output)", () => {
  const out = tmp("atlas-golden-");
  const run = spawnSync(process.execPath, [join(TOOLS, "compile-all.mjs"), "--source", GOLDEN, "--out", out], { encoding: "utf8" });
  const read = (file: string): { meta: Record<string, unknown> } & Record<string, any> =>
    JSON.parse(readFileSync(join(out, file), "utf8")) as { meta: Record<string, unknown> } & Record<string, any>;

  it("exits 0 and writes the four files to the requested directory", () => {
    expect(run.status, run.stderr).toBe(0);
    expect(readdirSync(out).sort()).toEqual(OUTPUTS.map((o) => o.file).sort());
  });

  it("names the golden file, repository-relative — not the sample", () => {
    const meta = read("fabric.json").meta;
    expect(meta.source).toBe("tests/golden/snapshot.json");
    expect(meta.sourceOrigin).toBe("repository-file");
  });

  it("all four outputs share one binding, on every key", () => {
    const metas = OUTPUTS.map((o) => read(o.file).meta);
    for (const k of SOURCE_BINDING_KEYS) {
      const values = new Set(metas.map((m) => JSON.stringify(m[k])));
      expect(values.size, `binding key ${k} differs between outputs`).toBe(1);
    }
  });

  it("compiles a real network, not an empty one", () => {
    const fabric = read("fabric.json");
    expect(fabric.devices.length).toBeGreaterThan(0);
    expect(fabric.findings.length).toBe((JSON.parse(readFileSync(GOLDEN, "utf8")) as { punchlist: unknown[] }).punchlist.length);
  });

  it("carries the evidence contract exactly where the golden carries it", () => {
    /* A successful compile means every golden pointer RESOLVED (compile-model.mjs refuses an unresolved
       one). The census below requires the golden to carry the contract at all, so a golden without it
       cannot make this pass vacuously. */
    const src = (JSON.parse(readFileSync(GOLDEN, "utf8")) as { punchlist: Record<string, unknown>[] }).punchlist;
    expect(src.filter((row) => Object.hasOwn(row, "evidence_refs")).length, "golden rows carrying evidence_refs (engine lane E1)").toBeGreaterThan(0);
    const fabric = read("fabric.json");
    src.forEach((row, i) => {
      const f = fabric.findings[i] as Record<string, unknown>;
      expect(f.evidenceRefs === null, `F${i + 1}`).toBe(!Object.hasOwn(row, "evidence_refs"));
      expect(f.evidenceBasis === null, `F${i + 1}`).toBe(!Object.hasOwn(row, "evidence_basis"));
      if (Array.isArray(f.evidenceRefs)) expect((f.evidenceRefs as unknown[]).length).toBe((row.evidence_refs as unknown[]).length);
    });
  });
});
