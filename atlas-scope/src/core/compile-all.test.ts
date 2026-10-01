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
 *     non-sample source, ANY in-repository directory but .local-data/ — Git-ignored ones included (dist/,
 *     node_modules/, review/…: R3 / refuter X2 / S1-R2V-2) — before anything is written;
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
import { cpSync, existsSync, lstatSync, mkdirSync, mkdtempSync, readdirSync, readFileSync, renameSync, rmSync, statSync, symlinkSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { afterAll, afterEach, beforeEach, describe, expect, it } from "vitest";

import { lfNormalise } from "../../tools/source-binding.mjs";
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

/* Sandboxes are removed by the test that made them (afterEach), not all at once at the end: removing every
   sandbox of this file in one afterAll took over 180 s under host contention (measured 2026-09-27, the hook
   timed out while each test had passed). A sandbox made outside any test (R6's, shared by its tests) is
   removed in afterAll. */
const sandboxes: string[] = [];
const perTest: string[] = [];
let inTest = false;
beforeEach(() => {
  inTest = true;
});
afterEach(() => {
  inTest = false;
  for (const d of perTest.splice(0)) rmSync(d, { recursive: true, force: true });
}, 120_000); // one to three sandbox trees; a hook, so the per-test limit does not cover it
afterAll(() => {
  for (const d of sandboxes) rmSync(d, { recursive: true, force: true });
});
const tmp = (prefix: string): string => {
  const d = mkdtempSync(join(tmpdir(), prefix));
  (inTest ? perTest : sandboxes).push(d);
  return d;
};

/** A copy of the package's tools and src skeleton, with the sample where the tools resolve it. */
function sandbox(opts: { withShipped?: boolean } = {}): { root: string; pkg: string; tools: string } {
  const root = tmp("atlas-compile-all-");
  const pkg = join(root, "atlas-scope");
  cpSync(TOOLS, join(pkg, "tools"), { recursive: true });
  // The engine contract the compiler imports (tools/lib/compile-model.mjs reads its vocabularies from it).
  cpSync(resolve(PKG, "contracts"), join(pkg, "contracts"), { recursive: true });
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

  /* S1-V3, split one command per test (vitest.config.ts: a large unit of work is split, not given a bigger limit;
     as one test of six compiles it timed out at 30 s under host contention, 2026-09-27). Every assertion is kept. */
  const mixedSetSandbox = () => {
    const sb = sandbox({ withShipped: true });
    const src = join(sb.root, SAMPLE_REL);
    const s = JSON.parse(readFileSync(src, "utf8")) as { script_version: string };
    s.script_version = "V0.0.0-mixed-set";
    writeFileSync(src, JSON.stringify(s));
    return sb;
  };
  it.each([["compile-snapshot.mjs"], ["compile-acl-bindings.mjs"], ["compile-rib-evidence.mjs"], ["compile-producer-emission.mjs"]])(
    "a per-file command (%s) refuses to leave its file bound to a different snapshot from its siblings (S1-V3)",
    (name) => {
      /* Measured by the verifier: after the sample changed, `node tools/compile-snapshot.mjs` exited 0 and
         left the three sidecars on the OLD digest — which sameSourceBinding then refuses silently, turning
         every ACL binding, RIB answer and emission flag into "unknown". */
      const { pkg, tools } = mixedSetSandbox();
      const before = snapshotOf(pkg);
      const r = spawnSync(process.execPath, [join(tools, name)], { encoding: "utf8" });
      expect(r.status, `${name}: ${r.stderr}`).toBe(2);
      expect(r.stderr, name).toMatch(/E_MIXED_SET/);
      expect(r.stderr, name).toMatch(/compile:data/);
      expect(snapshotOf(pkg), `${name} changed a file`).toEqual(before);
    },
  );

  it("after the set command rebuilds all four, a per-file command is consistent again (S1-V3 control)", () => {
    const { tools } = mixedSetSandbox();
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

/* A failed OPEN means what the check it replaced meant (2026-09-30 refuter). The source and every sibling are read
   with one open (compile-io.mjs `readRegularFile`, CodeQL js/file-system-race); that open's errnos were mapped only
   for ENOENT/ENOTDIR/EISDIR, so on POSIX a symbolic-link loop, a directory on the way that refuses, a socket or an
   over-long name escaped as a RAW error with a stack where `existsSync`/`isFile` had answered "no snapshot file",
   and a looping sibling became a mixed-set refusal where the exists-check had skipped it. This host cannot make
   most of those errnos, so each is INJECTED through the `beforeOpen` seam (a throw there is the open failing with
   it, as `beforeRestoreStep`'s throw is a file lock). */
const errno = (code: string): Error => Object.assign(new Error(`injected ${code}`), { code });
const openFailsWith = (code: string, only: (path: string) => boolean = () => true) => (path: string): void => {
  if (only(path)) throw errno(code);
};
const codeOf = (run: () => unknown): string => {
  try {
    run();
  } catch (e) {
    return e instanceof CompileError ? e.code : `RAW ${String((e as { code?: unknown }).code ?? e)}`;
  }
  return "no error";
};

describe("a failed open of the source means what the replaced exists/isFile check meant", () => {
  /** An external source file with the sample's bytes, and an output directory nothing may be written to. */
  const external = (): { source: string; out: string } => {
    const dir = tmp("atlas-open-source-");
    const source = join(dir, "snapshot.json");
    writeFileSync(source, readFileSync(resolve(REPO, SAMPLE_REL)));
    return { source, out: tmp("atlas-open-out-") };
  };

  it.each([["ENOENT"], ["ENOTDIR"], ["ELOOP"], ["ENAMETOOLONG"], ["EISDIR"], ["ENXIO"], ["EOPNOTSUPP"], ["ENODEV"]])(
    "%s: coded E_SOURCE_MISSING, never a raw error",
    (code) => {
      const { source, out } = external();
      expect(codeOf(() => compileToDisk({ toolsDir: TOOLS, source, out, hooks: { beforeOpen: openFailsWith(code) } }))).toBe("E_SOURCE_MISSING");
      expect(readdirSync(out), "nothing was written").toEqual([]);
    },
  );

  it("EACCES / EPERM on a directory on the way (the path cannot be reached): E_SOURCE_MISSING, as existsSync answered", () => {
    const out = tmp("atlas-open-out-");
    const source = join(tmp("atlas-open-source-"), "unreachable", "snapshot.json");
    for (const code of ["EACCES", "EPERM"]) {
      expect(codeOf(() => compileToDisk({ toolsDir: TOOLS, source, out, hooks: { beforeOpen: openFailsWith(code) } })), code).toBe("E_SOURCE_MISSING");
    }
  });

  it("EACCES / EPERM on a regular file that is there: its own code, E_SOURCE_UNREADABLE — distinguishable from no file", () => {
    const { source, out } = external();
    for (const code of ["EACCES", "EPERM"]) {
      expect(codeOf(() => compileToDisk({ toolsDir: TOOLS, source, out, hooks: { beforeOpen: openFailsWith(code) } })), code).toBe("E_SOURCE_UNREADABLE");
    }
    // The CLI prints it as a refusal (exit 1), not a stack: compile refused — <message>.
    expect(readdirSync(out)).toEqual([]);
  });

  it("an I/O failure that is none of those is thrown as it is (as the replaced read threw it)", () => {
    const { source, out } = external();
    expect(codeOf(() => compileToDisk({ toolsDir: TOOLS, source, out, hooks: { beforeOpen: openFailsWith("EIO") } }))).toBe("RAW EIO");
  });

  it("control: the same source with no injection compiles", () => {
    const { source, out } = external();
    let opened = 0;
    expect(codeOf(() => compileToDisk({ toolsDir: TOOLS, source, out, hooks: { beforeOpen: () => void (opened += 1) } }))).toBe("no error");
    expect(opened, "the seam sits on the source's open").toBeGreaterThan(0);
  });
});

describe("a failed open of a sibling output means what the replaced exists-check meant", () => {
  /* The per-file command writes aclBindings; its siblings are the other three files. The source was changed, so the
     shipped siblings on disk are bound to OTHER bytes: read, they refuse the write (E_MIXED_SET). */
  const SIBLING_FILES = new Set(OUTPUTS.filter((o) => o.key !== "aclBindings").map((o) => o.file));
  const isSibling = (p: string): boolean => SIBLING_FILES.has(p.split(/[\\/]/).pop() ?? "");
  const mixed = () => {
    const sb = sandbox({ withShipped: true });
    const src = join(sb.root, SAMPLE_REL);
    const s = JSON.parse(readFileSync(src, "utf8")) as { script_version: string };
    s.script_version = "V0.0.0-sibling-open";
    writeFileSync(src, JSON.stringify(s));
    return sb;
  };

  it("control: a readable sibling bound elsewhere refuses the write (E_MIXED_SET)", () => {
    const { tools } = mixed();
    let siblingsOpened = 0;
    const beforeOpen = (p: string): void => void (siblingsOpened += isSibling(p) ? 1 : 0);
    expect(codeOf(() => compileToDisk({ toolsDir: tools, only: "aclBindings", hooks: { beforeOpen } }))).toBe("E_MIXED_SET");
    expect(siblingsOpened, "the seam sits on the siblings' open").toBeGreaterThan(0);
  });

  it.each([["ELOOP"], ["ENAMETOOLONG"], ["ENOTDIR"]])("%s: no sibling reachable there, so it is skipped — not a mixed set", (code) => {
    const { pkg, tools } = mixed();
    const before = snapshotOf(pkg);
    expect(codeOf(() => compileToDisk({ toolsDir: tools, only: "aclBindings", hooks: { beforeOpen: openFailsWith(code, isSibling) } }))).toBe("no error");
    const after = snapshotOf(pkg);
    for (const o of OUTPUTS) {
      if (o.key === "aclBindings") expect(after.get(o.trackedPath), "its own file was written").not.toBe(before.get(o.trackedPath));
      else expect(after.get(o.trackedPath), `${o.trackedPath} was touched`).toBe(before.get(o.trackedPath));
    }
  });

  it("EACCES on a directory on the way to a sibling that is not there: skipped, as the exists-check skipped it", () => {
    const { pkg, tools } = sandbox(); // no shipped files: no sibling is there
    expect(codeOf(() => compileToDisk({ toolsDir: tools, only: "aclBindings", hooks: { beforeOpen: openFailsWith("EACCES", isSibling) } }))).toBe("no error");
    expect(existsSync(join(pkg, "src/forwarding/acl-bindings.json"))).toBe(true);
  });

  it.each([["EACCES"], ["EISDIR"], ["ENXIO"], ["EIO"]])("%s on a sibling that IS there: a sibling of unknown binding, so the write is refused", (code) => {
    const { tools } = mixed();
    expect(codeOf(() => compileToDisk({ toolsDir: tools, only: "aclBindings", hooks: { beforeOpen: openFailsWith(code, isSibling) } }))).toBe("E_MIXED_SET");
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

  it("SRC/data for the SAMPLE is refused exactly where it IS src/data: on a case-insensitive file system (S1-V2)", () => {
    /* The rule is identity, not spelling. Where the file system folds case (Windows, default macOS), "SRC" is
       the src/ directory and the sample must be refused like any other spelling of it. Where it does not
       (Linux CI), "SRC" is a different, new directory outside src/ — the sample is public, so compiling there
       is allowed, and src/ must still be untouched. Which branch runs is measured, never assumed from the
       platform name; both branches assert. */
    const { pkg, tools } = sandbox({ withShipped: true });
    const foldsCase = existsSync(join(pkg, "SRC"));
    const before = snapshotOf(pkg);
    const srcBefore = readdirSync(join(pkg, "src")).sort();
    const dataBefore = readdirSync(join(pkg, "src", "data")).sort();
    const r = cli(tools, ["--out", join(pkg, "SRC", "data")]);
    if (foldsCase) {
      expect(r.status, r.stderr).toBe(2);
      expect(r.stderr).toMatch(/E_OUT_REFUSED/);
      expect(snapshotOf(pkg)).toEqual(before);
    } else {
      expect(r.status, r.stderr).toBe(0);
      expect(existsSync(join(pkg, "SRC", "data", "fabric.json")), "it compiled to the separate SRC/ directory").toBe(true);
    }
    expect(readdirSync(join(pkg, "src")).sort(), "nothing new was created under src/").toEqual(srcBefore);
    expect(readdirSync(join(pkg, "src", "data")).sort(), "src/data was not written").toEqual(dataBefore);
  });

  it.each([["src/..data"], ["src./data"], ["src /data"], ["src/panels"]])(
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
      /* The class is "anywhere in the repository but .local-data/", not the one directory src/. This sandbox
         is not a Git work tree; the Git-owned cases (where ignored directories exist) are in the block above. */
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

  describe("in a tree Git OWNS, the only in-repository destination for a client compile is .local-data/ (R3 / X2 / S1-R2V-2)", () => {
    /* The sandbox above is not a Git work tree, so there only .local-data/ was ever "known ignored" and the
       Git-ignored branch of the old rule never ran. Here the sandbox IS a repository with the package's own
       .gitignore, so dist/, node_modules/, review/shots/ and review/_* really are ignored — the class the old
       rule accepted — and every one of them must still be refused. */
    const gitSandbox = (): { root: string; pkg: string; tools: string } => {
      const s = sandbox({ withShipped: true });
      cpSync(resolve(PKG, ".gitignore"), join(s.pkg, ".gitignore"));
      execFileSync("git", ["init", "-q"], { cwd: s.root, stdio: "pipe" });
      return s;
    };

    it.each([
      ["dist"], // Vite's outDir: AssessHub serves it unguarded at /scope, and the portable build bundles it
      ["dist/assets"],
      ["node_modules/x"],
      ["review"],
      ["review/shots"],
      ["review/_scratch/site-a"],
      ["public/data"],
      ["src/data"],
      ["."],
    ])("refuses --out %s for a non-sample source, writing nothing", (out) => {
      const { pkg, tools } = gitSandbox();
      const before = snapshotOf(pkg);
      const listing = (): string[] | null => (existsSync(join(pkg, out)) ? readdirSync(join(pkg, out)).sort() : null);
      const dirBefore = listing();
      const { file } = external();
      const r = cli(tools, ["--source", file, "--out", join(pkg, out)]);
      expect(r.status, r.stderr).toBe(2);
      expect(r.stderr).toMatch(/E_OUT_REFUSED/);
      expect(listing(), "nothing was created at the refused destination").toEqual(dirBefore);
      expect(snapshotOf(pkg)).toEqual(before);
    });

    it("the ignored cases above really are Git-ignored here (the refusal is not vacuous)", () => {
      const { root } = gitSandbox();
      for (const d of ["atlas-scope/dist/", "atlas-scope/node_modules/x/", "atlas-scope/review/shots/", "atlas-scope/review/_scratch/"]) {
        expect(spawnSync("git", ["check-ignore", "-q", "--", d], { cwd: root }).status, `${d} is ignored in the sandbox`).toBe(0);
      }
    });

    it("accepts .local-data/ and a directory outside the repository (positive controls)", () => {
      const { pkg, tools } = gitSandbox();
      const { file } = external();
      const a = cli(tools, ["--source", file, "--out", join(pkg, ".local-data", "site-a")]);
      expect(a.status, a.stderr).toBe(0);
      expect(existsSync(join(pkg, ".local-data", "site-a", "fabric.json"))).toBe(true);
      const outside = tmp("atlas-outside-git-");
      const b = cli(tools, ["--source", file, "--out", outside]);
      expect(b.status, b.stderr).toBe(0);
      expect(existsSync(join(outside, "fabric.json"))).toBe(true);
    });

    it("refuses .local-data/ itself when Git does NOT ignore it (the default destination is checked, not assumed)", () => {
      const { pkg, tools } = gitSandbox();
      writeFileSync(join(pkg, ".gitignore"), readFileSync(resolve(PKG, ".gitignore"), "utf8").split("\n").filter((l) => l.trim() !== ".local-data/").join("\n"));
      const { file } = external();
      const r = cli(tools, ["--source", file]);
      expect(r.status, r.stderr).toBe(2);
      expect(r.stderr).toMatch(/E_OUT_REFUSED/);
      expect(existsSync(join(pkg, ".local-data", "fabric.json"))).toBe(false);
    });

    /* R3-V2R-2 — .local-data/ ITSELF is placed by identity. Only --out used to be: the default destination was
       checked as text (Git ignores the NAME ".local-data/"), so a .local-data that is a junction or symbolic link
       to another in-repository directory took a client compile there — measured by the verifier, a junction to
       src/data overwrote the tracked fabric.json with exit 0, and one to dist/assets wrote into the directory
       AssessHub serves. The class is "a .local-data that is a second name for somewhere else", however it is
       reached (the default run, or --out below it). */
    describe(".local-data/ is placed by identity, not by its name (R3-V2R-2)", () => {
      const alias = (from: string, to: string): void => {
        mkdirSync(to, { recursive: true });
        symlinkSync(to, from, process.platform === "win32" ? "junction" : "dir");
      };
      it.each([
        ["src/data", "the default run"],
        ["src/data", "--out .local-data/x"],
        ["dist/assets", "the default run"],
        ["dist/assets", "--out .local-data/x"],
      ])("a .local-data that is a junction to %s is refused for %s, writing nothing", (target, how) => {
        const { pkg, tools } = gitSandbox();
        alias(join(pkg, ".local-data"), join(pkg, target));
        expect(lstatSync(join(pkg, ".local-data")).isSymbolicLink(), "precondition: .local-data is a link").toBe(true);
        const before = snapshotOf(pkg);
        const listing = readdirSync(join(pkg, target)).sort();
        const { file } = external();
        const r = cli(tools, ["--source", file, ...(how === "the default run" ? [] : ["--out", join(pkg, ".local-data", "x")])]);
        expect(r.status, r.stderr).toBe(2);
        expect(r.stderr).toMatch(/E_OUT_REFUSED/);
        expect(r.stderr).toMatch(/\.local-data/);
        expect(snapshotOf(pkg), "the tracked files are untouched").toEqual(before);
        expect(readdirSync(join(pkg, target)).sort(), `nothing was written into ${target}`).toEqual(listing);
      });

      it("a .local-data that is a link to a directory OUTSIDE the repository is refused too: the name must be the place", () => {
        const { pkg, tools } = gitSandbox();
        const outside = tmp("atlas-local-data-elsewhere-");
        alias(join(pkg, ".local-data"), outside);
        const { file } = external();
        const r = cli(tools, ["--source", file]);
        expect(r.status, r.stderr).toBe(2);
        expect(r.stderr).toMatch(/E_OUT_REFUSED/);
        expect(readdirSync(outside)).toEqual([]);
      });

      it("a plain .local-data directory is accepted (positive control)", () => {
        const { pkg, tools } = gitSandbox();
        mkdirSync(join(pkg, ".local-data"), { recursive: true });
        const { file } = external();
        const r = cli(tools, ["--source", file]);
        expect(r.status, r.stderr).toBe(0);
        expect(existsSync(join(pkg, ".local-data", "fabric.json"))).toBe(true);
      });
    });

    it("the SAMPLE keeps its freedom outside src/ in a Git-owned tree (it is public)", () => {
      const { pkg, tools } = gitSandbox();
      const r = cli(tools, ["--out", join(pkg, "review", "sample-out")]);
      expect(r.status, r.stderr).toBe(0);
    });

    /* R3-V1 — a SECOND NAME for an in-repository directory. Measured by the verifier: `--out
       \\localhost\c$\…\atlas-scope\src\data` (and …\dist\x) exited 0 and overwrote the tracked fabric.json
       with a client model, because realpath keeps a UNC root and a path-text rule then calls the directory
       "outside the repository". Containment is now decided by file identity (volume + file index). These run
       where the admin-share loopback is reachable — every spelling below is checked to BE the same directory
       before it is used, so a pass cannot come from a spelling that names nothing. */
    // Each case spawns Git and a compile; under host contention that exceeds the 30 s hang detector (measured 79 s).
    describe("containment is decided by file identity, not by spelling (R3-V1)", { timeout: 180_000 }, () => {
      const BS = "\\";
      const spellings: Record<string, (p: string) => string> = {
        "\\\\localhost\\<drive>$": (p) => `${BS}${BS}localhost${BS}${p[0]!.toLowerCase()}$${p.slice(2)}`,
        "\\\\127.0.0.1\\<drive>$": (p) => `${BS}${BS}127.0.0.1${BS}${p[0]!.toLowerCase()}$${p.slice(2)}`,
        "\\\\?\\UNC\\localhost\\<drive>$": (p) => `${BS}${BS}?${BS}UNC${BS}localhost${BS}${p[0]!.toLowerCase()}$${p.slice(2)}`,
      };
      const sameDir = (a: string, b: string): boolean => {
        try {
          const x = statSync(a, { bigint: true });
          const y = statSync(b, { bigint: true });
          return x.dev === y.dev && x.ino === y.ino && x.ino !== 0n;
        } catch {
          return false;
        }
      };
      const reachable = process.platform === "win32" && Object.values(spellings).every((f) => sameDir(PKG, f(PKG)));

      it.runIf(reachable).each(Object.keys(spellings).flatMap((name) => [
        [name, "src/data", false],
        [name, "src/data", true], // the sample too: the src/ rule holds for every source
        [name, "dist", false],
        [name, "dist/unc2", false],
        [name, "review/_scratch/site-a", false],
        [name, ".", false],
      ] as [string, string, boolean][]))("refuses --out %s spelling of %s (sample=%s), writing nothing", (name, out, sample) => {
        const { pkg, tools } = gitSandbox();
        const spelled = spellings[name]!(join(pkg, out));
        const listing = (): string[] | null => (existsSync(join(pkg, out)) ? readdirSync(join(pkg, out)).sort() : null);
        const before = snapshotOf(pkg);
        const dirBefore = listing();
        const { file } = external();
        const r = cli(tools, [...(sample ? [] : ["--source", file]), "--out", spelled]);
        expect(r.status, r.stderr).toBe(2);
        expect(r.stderr).toMatch(/E_OUT_REFUSED/);
        expect(listing(), "nothing was created at the refused destination").toEqual(dirBefore);
        expect(snapshotOf(pkg), "the tracked files are untouched").toEqual(before);
      });

      // Positive controls, one compile per test (vitest.config.ts: a large unit of work is split, not given a bigger limit).
      it.runIf(reachable).each(Object.keys(spellings).flatMap((name) => [[name, ".local-data/site-a"], [name, "a directory outside the repository"]] as [string, string][]))(
        "accepts the %s spelling of %s (positive control)",
        (name, where) => {
          const { pkg, tools } = gitSandbox();
          const { file } = external();
          const dest = where === ".local-data/site-a" ? join(pkg, ".local-data", "site-a") : tmp("atlas-outside-unc-");
          const r = cli(tools, ["--source", file, "--out", spellings[name]!(dest)]);
          expect(r.status, `${name}: ${r.stderr}`).toBe(0);
          expect(existsSync(join(dest, "fabric.json")), name).toBe(true);
        },
      );

      it("the spellings above are exercised on this host (win32 with the admin-share loopback reachable), or Windows says why not", () => {
        /* A block that always skips pins nothing, and a warning is not a verdict (verifier R3-V2R-4: this used to
           console.warn and assert only that `reachable` was a boolean, so an always-skip passed). The skip is now
           legal only for the reason WINDOWS states: it does not list this drive's administrative share. Where it
           lists it, the loopback spellings are expected to reach it and the identity cases must run; where the
           listing itself cannot be read, the reason is not established and this fails. */
        if (process.platform !== "win32") return void expect(reachable).toBe(false);
        const drive = PKG[0]!.toUpperCase();
        const shares = spawnSync("net", ["share"], { encoding: "utf8", windowsHide: true, timeout: 30_000 });
        expect(shares.status, `\`net share\` could not be read (${String(shares.error ?? shares.stderr)}), so a skip has no stated reason`).toBe(0);
        const listed = new RegExp(`^${drive}\\$\\s`, "m").test(shares.stdout ?? "");
        if (listed) expect(reachable, `Windows lists the ${drive}$ administrative share, so the identity cases must run here`).toBe(true);
        else expect(reachable, `Windows lists no ${drive}$ administrative share, so the identity cases cannot run here`).toBe(false);
      });
    });

    /* R3-V2 — every work tree of the repository is "the repository". Measured by the verifier: from a LINKED
       worktree, `--out <main checkout>/atlas-scope/dist/assets` (the directory AssessHub serves at /scope from
       the main checkout) and `<main>/webapp/frontend/dist` exited 0 for a client snapshot. */
    describe("from a linked worktree, every other work tree of the repository is the repository too (R3-V2)", { timeout: 180_000 }, () => {
      const gitIn = (cwd: string, args: string[]): void =>
        void execFileSync("git", ["-c", "user.name=atlas-test", "-c", "user.email=atlas-test@example.invalid", ...args], { cwd, stdio: "pipe" });
      /** A Git-owned main checkout, a linked worktree NESTED in it (like .claude/worktrees/<name>) with its own copy of the package, and a linked worktree OUTSIDE it. */
      const worktrees = () => {
        const main = gitSandbox();
        gitIn(main.root, ["commit", "-q", "--allow-empty", "-m", "sandbox"]);
        const nested = join(main.root, ".claude", "worktrees", "wt");
        gitIn(main.root, ["worktree", "add", "-q", "--detach", nested]);
        const sibling = join(tmp("atlas-wt-sibling-"), "wt2");
        gitIn(main.root, ["worktree", "add", "-q", "--detach", sibling]);
        const nestedPkg = join(nested, "atlas-scope");
        cpSync(TOOLS, join(nestedPkg, "tools"), { recursive: true });
        cpSync(resolve(PKG, "contracts"), join(nestedPkg, "contracts"), { recursive: true });
        cpSync(resolve(PKG, ".gitignore"), join(nestedPkg, ".gitignore"));
        mkdirSync(join(nestedPkg, "src", "data"), { recursive: true });
        mkdirSync(join(nested, "webapp", "sample_data"), { recursive: true });
        writeFileSync(join(nested, SAMPLE_REL), readFileSync(resolve(REPO, SAMPLE_REL)));
        mkdirSync(join(sibling, "atlas-scope", "src", "data"), { recursive: true });
        return { main, nested, nestedPkg, nestedTools: join(nestedPkg, "tools"), sibling };
      };

      it("git really lists all three as work trees of one repository (the cases below are not vacuous)", () => {
        const w = worktrees();
        const listed = execFileSync("git", ["worktree", "list", "--porcelain"], { cwd: w.nested, encoding: "utf8" });
        expect(listed.split(/\r?\n/).filter((l) => l.startsWith("worktree ")).length).toBe(3);
      });

      it.each([
        ["the main checkout's atlas-scope/dist/assets", (w: ReturnType<typeof worktrees>) => join(w.main.pkg, "dist", "assets")],
        ["the main checkout's webapp/frontend/dist", (w: ReturnType<typeof worktrees>) => join(w.main.root, "webapp", "frontend", "dist")],
        ["the main checkout's .local-data/ (another checkout's, not this package's)", (w: ReturnType<typeof worktrees>) => join(w.main.pkg, ".local-data", "x")],
        ["a sibling worktree outside the main checkout", (w: ReturnType<typeof worktrees>) => join(w.sibling, "atlas-scope", "dist")],
        ["the repository's common Git directory", (w: ReturnType<typeof worktrees>) => join(w.main.root, ".git", "atlas-out")],
      ])("a client compile run from the nested worktree refuses --out into %s", (_why, where) => {
        const w = worktrees();
        const out = where(w);
        const existedBefore = existsSync(out);
        const { file } = external();
        const r = cli(w.nestedTools, ["--source", file, "--out", out]);
        expect(r.status, r.stderr).toBe(2);
        expect(r.stderr).toMatch(/E_OUT_REFUSED/);
        expect(existsSync(join(out, "fabric.json"))).toBe(false);
        if (!existedBefore) expect(existsSync(out), "nothing was created at the refused destination").toBe(false);
      });

      it("the sample from the nested worktree may not write another work tree's src/ (the src/ rule spans work trees)", () => {
        const w = worktrees();
        const r = cli(w.nestedTools, ["--out", join(w.sibling, "atlas-scope", "src", "data")]);
        expect(r.status, r.stderr).toBe(2);
        expect(r.stderr).toMatch(/E_OUT_REFUSED/);
        expect(readdirSync(join(w.sibling, "atlas-scope", "src", "data"))).toEqual([]);
      });

      it("a worktree git no longer LISTS where it is (moved by hand) is still the repository: Git run inside it names our common directory", () => {
        /* `git worktree list` keeps the OLD path of a worktree moved without `git worktree move`, yet Git still
           works inside the moved directory. The listed roots miss it; asking Git from inside the destination does not. */
        const w = worktrees();
        const moved = join(dirname(w.sibling), "wt2-moved");
        renameSync(w.sibling, moved);
        const listed = execFileSync("git", ["worktree", "list", "--porcelain"], { cwd: w.main.root, encoding: "utf8" });
        expect(listed.includes("wt2-moved"), "precondition: git does not list the moved worktree").toBe(false);
        expect(spawnSync("git", ["rev-parse", "--git-common-dir"], { cwd: moved }).status, "precondition: Git still works inside it").toBe(0);
        const { file } = external();
        const r = cli(w.nestedTools, ["--source", file, "--out", join(moved, "atlas-scope", "dist")]);
        expect(r.status, r.stderr).toBe(2);
        expect(r.stderr).toMatch(/E_OUT_REFUSED/);
        expect(existsSync(join(moved, "atlas-scope", "dist"))).toBe(false);
      });

      it("a separate Git repository NESTED inside another work tree of ours (a vendored clone) is still inside that work tree", () => {
        /* Git run inside it names ITS OWN common directory, so the common-directory question alone would call it
           outside; the listed work-tree roots, placed by identity, do not. */
        const w = worktrees();
        const vendored = join(w.main.root, "vendor", "clone");
        mkdirSync(vendored, { recursive: true });
        execFileSync("git", ["init", "-q"], { cwd: vendored, stdio: "pipe" });
        const { file } = external();
        const r = cli(w.nestedTools, ["--source", file, "--out", join(vendored, "out")]);
        expect(r.status, r.stderr).toBe(2);
        expect(r.stderr).toMatch(/E_OUT_REFUSED/);
        expect(existsSync(join(vendored, "out"))).toBe(false);
      });

      it("a client compile run from the MAIN checkout refuses --out into a linked worktree outside it", () => {
        const w = worktrees();
        const { file } = external();
        const r = cli(w.main.tools, ["--source", file, "--out", join(w.sibling, "review")]);
        expect(r.status, r.stderr).toBe(2);
        expect(r.stderr).toMatch(/E_OUT_REFUSED/);
      });

      it("positive controls: the nested worktree's OWN .local-data/, and a directory outside every work tree, are accepted", () => {
        const w = worktrees();
        const { file } = external();
        const a = cli(w.nestedTools, ["--source", file, "--out", join(w.nestedPkg, ".local-data", "site-a")]);
        expect(a.status, a.stderr).toBe(0);
        expect(existsSync(join(w.nestedPkg, ".local-data", "site-a", "fabric.json"))).toBe(true);
        const outside = tmp("atlas-outside-wt-");
        const b = cli(w.nestedTools, ["--source", file, "--out", outside]);
        expect(b.status, b.stderr).toBe(0);
        expect(existsSync(join(outside, "fabric.json"))).toBe(true);
      });
    });
  });

  describe("the TRACKED set is compiled only from the committed (LF) form of the sample (R3-V4)", { timeout: 180_000 }, () => {
    /* sourceExactSha256 is the sha256 of the bytes AS READ (owner decision R3). On a core.autocrlf=true checkout
       the default run would therefore write this checkout's CRLF digest into all four COMMITTED files, and the
       tracked set would differ per clone (provenance's "tracked model == compile of the committed bytes" goes
       red). The default run refuses such bytes; the same bytes compile elsewhere with --out. */
    const crlfSample = (root: string): Buffer => {
      const lf = readFileSync(join(root, SAMPLE_REL));
      const crlf = Buffer.from(lf.toString("latin1").split("\r\n").join("\n").split("\n").join("\r\n"), "latin1");
      writeFileSync(join(root, SAMPLE_REL), crlf);
      return crlf;
    };

    it.each([["compile-all.mjs"], ["compile-snapshot.mjs"], ["compile-acl-bindings.mjs"], ["compile-rib-evidence.mjs"], ["compile-producer-emission.mjs"]])(
      "%s refuses a CRLF sample for the tracked files (E_TRACKED_SOURCE_FORM), writing nothing",
      (name) => {
        const { root, pkg, tools } = sandbox({ withShipped: true });
        crlfSample(root);
        const before = snapshotOf(pkg);
        const r = spawnSync(process.execPath, [join(tools, name)], { encoding: "utf8" });
        expect(r.status, r.stderr).toBe(1);
        expect(r.stderr).toMatch(/E_TRACKED_SOURCE_FORM/);
        expect(snapshotOf(pkg)).toEqual(before);
      },
    );

    it("the same CRLF bytes compile to a directory outside src/ with --out, recording their own exact digest (control)", () => {
      const { root, pkg, tools } = sandbox();
      const crlf = crlfSample(root);
      const out = join(pkg, "review", "crlf-out");
      const r = cli(tools, ["--out", out]);
      expect(r.status, r.stderr).toBe(0);
      const m = (JSON.parse(readFileSync(join(out, "fabric.json"), "utf8")) as { meta: Record<string, unknown> }).meta;
      expect(m.sourceExactSha256).toBe(`sha256:${sha256(crlf)}`);
      expect(m.sourceExactSha256).not.toBe(`sha256:${String(m.sourceSha256)}`);
    });

    /* R3-V2R-3 — the refusal above must not fire on a FRESH CLONE of this repository on a host whose Git
       converts line endings (core.autocrlf=true is this host's system default). What prevents it is the
       repository's own `.gitattributes` pin for the sample; this proves the pin does it, by cloning a repository
       that holds the sample and the REAL .gitattributes under core.autocrlf=true and compiling the clone — and,
       as the control, that the same clone WITHOUT the sample's pin checks out CRLF and is refused. */
    describe("a fresh clone under core.autocrlf=true compiles the tracked set, because of the .gitattributes pin (R3-V2R-3)", () => {
      const git = (cwd: string, args: string[]): string =>
        execFileSync("git", ["-c", "core.autocrlf=true", "-c", "user.name=atlas-test", "-c", "user.email=atlas-test@example.invalid", ...args], {
          cwd,
          encoding: "utf8",
          stdio: ["ignore", "pipe", "pipe"],
        });
      const realAttributes = readFileSync(resolve(REPO, ".gitattributes"), "utf8");
      const samplePin = /^webapp\/sample_data\/\S+\s.*\beol=lf\b/m;
      const cloneWith = (attributes: string): { clone: string; tools: string; pkg: string } => {
        const origin = tmp("atlas-autocrlf-origin-");
        git(origin, ["init", "-q"]);
        writeFileSync(join(origin, ".gitattributes"), attributes);
        mkdirSync(join(origin, "webapp", "sample_data"), { recursive: true });
        writeFileSync(join(origin, SAMPLE_REL), lfNormalise(readFileSync(resolve(REPO, SAMPLE_REL))));
        git(origin, ["add", "-A"]);
        git(origin, ["commit", "-q", "-m", "sample"]);
        const clone = join(tmp("atlas-autocrlf-clone-"), "repo");
        git(dirname(clone), ["clone", "-q", "--config", "core.autocrlf=true", origin, clone]);
        // The package beside the clone's sample, as a checkout of this repository has it.
        const pkg = join(clone, "atlas-scope");
        cpSync(TOOLS, join(pkg, "tools"), { recursive: true });
        cpSync(resolve(PKG, "contracts"), join(pkg, "contracts"), { recursive: true });
        for (const o of OUTPUTS) mkdirSync(dirname(join(pkg, o.trackedPath)), { recursive: true });
        return { clone, tools: join(pkg, "tools"), pkg };
      };

      it("the repository's .gitattributes pins the sample LF (the premise of the clone below)", () => {
        expect(realAttributes).toMatch(samplePin);
      });

      it("with the repository's .gitattributes: the clone's sample is LF and the default run writes the tracked set, byte-identical", () => {
        const { clone, pkg, tools } = cloneWith(realAttributes);
        expect(git(clone, ["config", "--get", "core.autocrlf"]).trim(), "the clone converts line endings").toBe("true");
        expect(git(clone, ["check-attr", "eol", "--", SAMPLE_REL]).trim()).toBe(`${SAMPLE_REL}: eol: lf`);
        expect(readFileSync(join(clone, SAMPLE_REL), "latin1").includes("\r\n"), "the clone checked the sample out LF").toBe(false);
        const r = cli(tools, []);
        expect(r.status, r.stderr).toBe(0);
        for (const o of OUTPUTS) {
          expect(readFileSync(join(pkg, o.trackedPath)).equals(readFileSync(resolve(PKG, o.trackedPath))), o.trackedPath).toBe(true);
        }
      });

      it("control — the same clone WITHOUT the sample's pin checks it out CRLF, and the tracked compile is refused", () => {
        const { clone, pkg, tools } = cloneWith(realAttributes.split("\n").filter((l) => !samplePin.test(l)).join("\n"));
        expect(git(clone, ["check-attr", "eol", "--", SAMPLE_REL]).trim()).toBe(`${SAMPLE_REL}: eol: unspecified`);
        expect(readFileSync(join(clone, SAMPLE_REL), "latin1").includes("\r\n"), "without the pin, autocrlf checks it out CRLF").toBe(true);
        const r = cli(tools, []);
        expect(r.status, r.stderr).toBe(1);
        expect(r.stderr).toMatch(/E_TRACKED_SOURCE_FORM/);
        for (const o of OUTPUTS) expect(existsSync(join(pkg, o.trackedPath)), o.trackedPath).toBe(false);
      });
    });

    it("an LF sample still writes the tracked files (control: the refusal is about the form, not the source)", () => {
      const { pkg, tools } = sandbox();
      const r = cli(tools, []);
      expect(r.status, r.stderr).toBe(0);
      const m = (JSON.parse(readFileSync(join(pkg, "src", "data", "fabric.json"), "utf8")) as { meta: Record<string, unknown> }).meta;
      expect(m.sourceExactSha256).toBe(`sha256:${String(m.sourceSha256)}`);
    });
  });

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

  it("in the real repository, a Git-IGNORED directory is refused as firmly as a tracked one (R3 / refuter X2)", () => {
    /* Before (S1-V4's rule): any directory Git ignores was accepted, so review/_scratch/ — and dist/, which
       AssessHub serves without its API guard at /scope — took a client compile with exit 0. Ignored is a
       statement about COMMITTING, not about PUBLISHING. Owner rule: .local-data/ or outside the repository. */
    const { file } = external();
    for (const where of [join(PKG, "review", "_scratch", `r3-compile-out-${process.pid}`), join(PKG, "docs", `r3-compile-out-${process.pid}`)]) {
      try {
        const no = cli(TOOLS, ["--source", file, "--out", where]);
        expect(no.status, no.stderr).toBe(2);
        expect(no.stderr).toMatch(/E_OUT_REFUSED/);
        expect(existsSync(where)).toBe(false);
      } finally {
        // A regression (or a mutation check) that DOES write there must not leave client-shaped data behind.
        rmSync(where, { recursive: true, force: true });
      }
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
