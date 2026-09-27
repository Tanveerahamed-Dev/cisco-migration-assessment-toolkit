/**
 * compile-io.mjs — the Node side of the compiler: read the snapshot ONCE, validate it, bind it,
 * compile the whole set with tools/lib/compile-model.mjs, and write it so that either every file lands
 * or none does. Every `tools/compile-*.mjs` is a thin command over `runCompileCli` here.
 *
 * WHERE OUTPUT GOES — decided by WHOSE bytes they are, because the four files under src/ are tracked
 * in Git and a real assessment compiled there is one `git add` away from publishing client hostnames,
 * addresses and serials:
 *   - the tracked sample (source-binding.mjs SOURCE_REL), no --out: the four tracked files under src/;
 *   - --out <dir>: <dir>/fabric.json, acl-bindings.json, rib-evidence.json, producer-emission.json;
 *   - any other source, no --out: the git-ignored `atlas-scope/.local-data/`;
 *   - --out anywhere inside src/ is REFUSED (E_OUT_REFUSED), whatever the source: the tracked files
 *     are reached only by the default sample run;
 *   - for any source other than the sample, --out anywhere else inside the repository is REFUSED unless
 *     it is under .local-data/ or Git itself reports the directory ignored. The class is "a location Git
 *     would track or Vite would bundle" (public/, review/, docs/, the package root …), not one named
 *     directory; outside the repository the caller owns the location.
 * Containment is decided on the CANONICAL path — the real path of the nearest existing ancestor (case,
 * junctions, 8.3 names resolved) — by whole path segments ("src/..data" is inside src/), and a path
 * component ending in a dot or a space is refused outright: Win32 drops them, so "src./data" can name
 * src/data to one API and a new directory to another.
 *
 * WHICH ORIGIN — "repository-file" is a file GIT TRACKS in this repository (named by its repository
 * path, its exact bytes being the blob Git stores); any other file — including an untracked or ignored
 * one inside the repository — is an "external-file", named by its file name and bound to the bytes as
 * read. Where Git does not own the tree at all (a copied package, a sandbox) there is no tracked/untracked
 * distinction to draw, and containment in the tree decides.
 *
 * ATOMICITY. The set is compiled in memory, written to a staging directory beside its destination
 * (same volume, so a rename is a rename), re-read and checked (every file parses, all four carry one
 * binding), and only then moved into place, one rename per file with the previous file set aside. A
 * failure at any point — compile, write, check, or midway through the renames — restores the previous
 * files and removes the staging directory. If a restore itself fails (a Windows file lock), the staging
 * directory holding the previous file(s) is KEPT and named in the refusal: it is then their only copy.
 * A per-file command (compile-snapshot.mjs …) writes one file of the set, so it refuses (E_MIXED_SET)
 * when a sibling already on disk is bound to a different snapshot: that would be a mixed set, which the
 * app refuses silently at runtime.
 */
import { spawnSync } from "node:child_process";
import { existsSync, mkdirSync, mkdtempSync, readFileSync, realpathSync, renameSync, rmSync, statSync, writeFileSync } from "node:fs";
import { basename, dirname, isAbsolute, join, parse, relative, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";
import { bindSource, SOURCE_REL, workingTreeDigest } from "../source-binding.mjs";
import { BINDING_KEYS, CompileError, compileAll, OUTPUTS, serialiseCompiled } from "./compile-model.mjs";
import { assertValidSnapshot } from "./validate-snapshot.mjs";

/** Exit codes: 0 compiled; 1 the snapshot (or its compile, or the write) was refused; 2 the command itself was refused. */
const USAGE_CODES = new Set(["E_USAGE", "E_OUT_REFUSED", "E_SOURCE_LABEL", "E_MIXED_SET"]);

const USAGE = `usage: node tools/compile-all.mjs [--source <snapshot.json>] [--out <dir>] [--label <name>] [--allow-legacy]
  --source <file>  the engine snapshot to compile (default: the tracked sample, ${SOURCE_REL})
  --out <dir>      where to write the four files (default: the tracked files for the sample,
                   atlas-scope/.local-data/ for anything else). Never inside src/; for anything but
                   the sample, never a repository directory Git does not ignore
  --label <name>   the file name recorded as meta.source for a file Git does not track
  --allow-legacy   read a snapshot with no schema tag as collect_parse_snapshot/1, and say so in meta`;

/**
 * @typedef {"fabric" | "aclBindings" | "ribEvidence" | "producerEmission"} OutputKey
 * @typedef {{ source?: string; out?: string; label?: string; allowLegacy: boolean; help: boolean }} CompileArgs
 */

/** @param {string[]} argv @returns {CompileArgs} */
export function parseCompileArgs(argv) {
  /** @type {CompileArgs} */
  const args = { allowLegacy: false, help: false };
  for (let i = 0; i < argv.length; i += 1) {
    const a = /** @type {string} */ (argv[i]);
    const takeValue = () => {
      const v = argv[i + 1];
      if (v === undefined || v.startsWith("--")) throw new CompileError("E_USAGE", `${a} needs a value.\n${USAGE}`);
      i += 1;
      return v;
    };
    if (a === "--source") args.source = takeValue();
    else if (a === "--out") args.out = takeValue();
    else if (a === "--label") args.label = takeValue();
    else if (a === "--allow-legacy") args.allowLegacy = true;
    else if (a === "--help" || a === "-h") args.help = true;
    else throw new CompileError("E_USAGE", `unknown argument ${JSON.stringify(a)}.\n${USAGE}`);
  }
  return args;
}

/**
 * Whether `child` is `parent` or inside it — by whole path SEGMENTS: a child named "..data" is inside
 * (the old `startsWith("..")` test called it outside, verifier S1-V2). Both paths must be canonical.
 * @param {string} parent @param {string} child
 */
const within = (parent, child) => {
  const r = relative(parent, child);
  if (r === "") return true;
  if (isAbsolute(r)) return false;
  return r.split(sep)[0] !== "..";
};
const posix = (/** @type {string} */ p) => p.split(sep).join("/");

/** Characters Win32 reserves in a path component (the drive colon lives in the root, not a component). */
const WIN32_RESERVED = /[<>:"|?*]/;

/**
 * The canonical form of a path that may not exist yet: the real path of its nearest existing ancestor
 * (case, junctions and short names resolved by the OS) with the remaining components appended. A
 * component ending in a dot or a space, or (on Windows) carrying a reserved character, is refused:
 * Win32 silently drops a trailing dot or space, so such a name reaches a DIFFERENT directory depending on
 * which API resolves it — measured: "src./data" is absent to realpath yet a temp directory created under
 * it landed in src/data.
 * @param {string} p @param {string} what  how the path is named in a refusal (e.g. "--out")
 */
function canonicalPath(p, what) {
  const abs = resolve(p);
  const { root } = parse(abs);
  const segs = abs.slice(root.length).split(sep).filter((s) => s !== "");
  for (const s of segs) {
    if (/[. ]$/.test(s) || (process.platform === "win32" && WIN32_RESERVED.test(s))) {
      throw new CompileError(
        "E_OUT_REFUSED",
        `${what} ${p} has a path component ${JSON.stringify(s)} that ends in a dot or a space or carries a reserved character. ` +
          `Windows resolves such a name to a different directory ("src." is src), so the location cannot be checked and is refused.`,
      );
    }
  }
  let i = segs.length;
  while (i > 0 && !existsSync(join(root, ...segs.slice(0, i)))) i -= 1;
  return join(realpathSync.native(join(root, ...segs.slice(0, i))), ...segs.slice(i));
}

/**
 * What Git says about this repository — or null where Git does not own it (no Git, not a work tree, or a
 * work tree whose top level is not this repository, e.g. a sandbox copy under a directory that is one).
 * @param {string} repo  canonical repository root
 */
function gitContext(repo) {
  /** @param {string[]} args */
  const git = (args) => spawnSync("git", ["-C", repo, ...args], { encoding: "utf8", stdio: ["ignore", "pipe", "pipe"], windowsHide: true });
  const top = git(["rev-parse", "--show-toplevel"]);
  if (top.error || top.status !== 0) return null;
  const topDir = top.stdout.trim();
  if (topDir === "" || !existsSync(topDir) || relative(realpathSync.native(topDir), repo) !== "") return null;
  return {
    /** Whether Git tracks the repository-relative POSIX path `rel`. @param {string} rel */
    tracked: (rel) => git(["ls-files", "--error-unmatch", "--", rel]).status === 0,
    /** Whether Git ignores the repository-relative directory `rel` (which need not exist). @param {string} rel */
    ignoredDir: (rel) => rel !== "" && git(["check-ignore", "-q", "--", `${rel}/`]).status === 0,
  };
}

/**
 * @typedef {{
 *   toolsDir: string;
 *   source?: string;
 *   out?: string;
 *   label?: string;
 *   allowLegacy?: boolean;
 *   only?: OutputKey;
 *   hooks?: { beforeCommitStep?: (index: number, key: OutputKey) => void; beforeRestoreStep?: (index: number, key: OutputKey) => void };
 * }} CompileToDiskOptions
 */

/**
 * Compile one snapshot to disk as a set. Throws a CompileError for every refusal; on ANY throw the
 * previous files are left exactly as they were.
 * @param {CompileToDiskOptions} o
 */
export function compileToDisk(o) {
  const pkg = realpathSync.native(resolve(o.toolsDir, ".."));
  const repo = resolve(pkg, "..");
  const git = gitContext(repo);
  const sample = resolve(repo, SOURCE_REL);
  const sourcePath = o.source === undefined ? sample : resolve(o.source);
  const sourceCanon = existsSync(sourcePath) ? realpathSync.native(sourcePath) : sourcePath;
  const isSample = relative(existsSync(sample) ? realpathSync.native(sample) : sample, sourceCanon) === "";

  /* Where the set goes (see the header). Decided and refused BEFORE the source is even read. */
  const srcDir = resolve(pkg, "src");
  const localData = join(pkg, ".local-data");
  /** @type {string | undefined} */
  let outDir;
  if (o.out !== undefined) {
    outDir = canonicalPath(o.out, "--out");
    if (within(srcDir, outDir)) {
      throw new CompileError(
        "E_OUT_REFUSED",
        `--out ${o.out} is inside ${posix(relative(repo, srcDir))}/, whose compiled files are tracked in Git. The tracked files are ` +
          `written only by the default sample run; compile anything else to a directory outside src/ (default: .local-data/).`,
      );
    }
    if (!isSample && within(repo, outDir) && !within(localData, outDir) && !(git !== null && git.ignoredDir(posix(relative(repo, outDir))))) {
      throw new CompileError(
        "E_OUT_REFUSED",
        `--out ${o.out} is inside the repository and Git does not ignore it${git === null ? " (Git does not own this tree, so only .local-data/ is known to be ignored)" : ""}: ` +
          `a compiled assessment there is one \`git add\` — or one build of a bundled directory — away from publishing client data. ` +
          `Compile it to ${posix(relative(repo, localData))}/ (the default), a Git-ignored directory, or a directory outside the repository.`,
      );
    }
  }
  /** Every output's destination, before `only` narrows what this run writes. */
  const allTargets = OUTPUTS.map((t) => ({
    key: /** @type {OutputKey} */ (t.key),
    file: t.file,
    path: outDir !== undefined ? join(outDir, t.file) : isSample ? resolve(pkg, t.trackedPath) : join(localData, t.file),
  }));
  const targets = allTargets.filter((t) => o.only === undefined || t.key === o.only);
  const stagingParent = outDir ?? localData;

  /* Which name the source is recorded under (see the header, WHICH ORIGIN). */
  const inRepo = within(repo, sourceCanon);
  const repoRel = posix(relative(repo, sourceCanon));
  const isRepositoryFile = inRepo && (git === null || git.tracked(repoRel));
  if (isRepositoryFile && o.label !== undefined) {
    throw new CompileError("E_SOURCE_LABEL", `--label names a file Git does not track; ${repoRel} is tracked, so it is named by its repository path.`);
  }
  /** @type {import("./compile-model.mjs").SourceLabel} */
  const label = isRepositoryFile
    ? { source: repoRel, sourceOrigin: "repository-file" }
    : { source: o.label ?? basename(sourceCanon), sourceOrigin: "external-file" };

  /* ONE read of the bytes: everything below — validation, binding, compile — reads this buffer. */
  if (!existsSync(sourcePath) || !statSync(sourcePath).isFile()) {
    throw new CompileError("E_SOURCE_MISSING", `there is no snapshot file at ${inRepo ? repoRel : label.source + " (outside the repository)"}.`);
  }
  const bytes = readFileSync(sourcePath);
  const v = assertValidSnapshot(bytes, { allowLegacy: o.allowLegacy === true });
  const binding = bindSource(bytes, label);
  const set = compileAll(v.snap, binding, { schemaAssumed: v.schemaAssumed });
  const texts = serialiseCompiled(set);

  /* A per-file command writes one file of a SET: refuse if a sibling on disk is bound elsewhere. */
  if (o.only !== undefined) {
    const mine = /** @type {{ file: string }} */ (allTargets.find((t) => t.key === o.only));
    for (const sib of allTargets.filter((t) => t.key !== o.only && existsSync(t.path))) {
      /** @type {Record<string, unknown> | null} */
      let meta = null;
      try {
        meta = /** @type {{ meta?: Record<string, unknown> }} */ (JSON.parse(readFileSync(sib.path, "utf8"))).meta ?? null;
      } catch {
        meta = null;
      }
      const differs = meta === null ? ["its meta"] : BINDING_KEYS.filter((k) => meta?.[k] !== binding[k]);
      if (differs.length > 0) {
        throw new CompileError(
          "E_MIXED_SET",
          `this command writes only ${mine.file}, and ${sib.file} beside it is bound to a different snapshot (${differs.join(", ")} ` +
            `differ${meta !== null && differs.includes("sourceSha256") ? `: ${String(meta.sourceSha256).slice(0, 12)}… there, ${binding.sourceSha256.slice(0, 12)}… here` : ""}). ` +
            `Writing one file would leave a mixed set, which the app refuses without a build error (every ACL binding, routing answer ` +
            `and emission flag would read "unknown"). Rebuild the whole set: npm run compile:data (node tools/compile-all.mjs, with the same arguments). Nothing was written.`,
        );
      }
    }
  }

  /* Stage, check, commit. Any failure here is either a CompileError already, or an I/O failure that is
     reported with a code (E_WRITE_FAILED) and its cause — never a raw ENOENT. */
  /** @param {unknown} e */
  const coded = (e) =>
    e instanceof CompileError
      ? e
      : new CompileError("E_WRITE_FAILED", `writing the compiled set failed (${e instanceof Error ? e.message : String(e)}); the previous files are unchanged.`, null, [], { cause: e });
  /** @type {string} */
  let staging;
  try {
    mkdirSync(stagingParent, { recursive: true });
    staging = mkdtempSync(join(stagingParent, ".compile-staging-"));
  } catch (e) {
    throw coded(e);
  }
  /** @type {{ key: OutputKey; path: string; prev: string | null }[]} */
  const committed = [];
  let keepStaging = false;
  try {
    for (const t of targets) writeFileSync(join(staging, `${t.key}.new`), texts[t.key], "utf8");
    for (const t of targets) {
      const doc = /** @type {{ meta?: Record<string, unknown> }} */ (JSON.parse(readFileSync(join(staging, `${t.key}.new`), "utf8")));
      for (const k of BINDING_KEYS) {
        if (doc.meta?.[k] !== binding[k]) {
          throw new CompileError("E_STAGED_SET", `the staged ${t.key} does not carry the set's ${k}; nothing was written.`);
        }
      }
    }
    targets.forEach((t, index) => {
      o.hooks?.beforeCommitStep?.(index, t.key);
      mkdirSync(dirname(t.path), { recursive: true });
      /** @type {string | null} */
      let prev = null;
      if (existsSync(t.path)) {
        prev = join(staging, `${t.key}.prev`);
        renameSync(t.path, prev);
      }
      committed.push({ key: t.key, path: t.path, prev });
      renameSync(join(staging, `${t.key}.new`), t.path);
    });
  } catch (e) {
    /* Roll back in reverse: every file this run moved is put back exactly as it was. Each step is
       guarded, and a step that fails leaves its previous file in the staging directory — which is then
       KEPT, because it holds the only copy (verifier S1-V5). */
    /** @type {string[]} */
    const stuck = [];
    [...committed].reverse().forEach((c, index) => {
      try {
        o.hooks?.beforeRestoreStep?.(index, c.key);
        if (c.prev !== null) renameSync(c.prev, c.path); // replaces the new file in one step
        else rmSync(c.path, { force: true });
      } catch (re) {
        stuck.push(`${basename(c.path)} (${re instanceof Error ? re.message : String(re)})`);
      }
    });
    if (stuck.length > 0) {
      keepStaging = true;
      const where = within(repo, staging) ? posix(relative(repo, staging)) : staging;
      throw new CompileError(
        "E_ROLLBACK_INCOMPLETE",
        `writing the compiled set failed (${e instanceof Error ? e.message : String(e)}), and putting back the previous ` +
          `${stuck.join("; ")} failed too. The previous file(s) are kept, as <name>.prev, in ${where} — move them back by hand. ` +
          `Every other file is as it was.`,
        null,
        [],
        { cause: e },
      );
    }
    throw coded(e);
  } finally {
    if (!keepStaging) rmSync(staging, { recursive: true, force: true });
  }

  return {
    sourcePath,
    binding,
    warnings: v.warnings,
    set,
    written: targets.map((t) => t.path),
    workingTree: workingTreeDigest(bytes),
  };
}

/**
 * Run a compile command: parse `argv`, compile, print a summary; return the exit code.
 * @param {string} moduleUrl  `import.meta.url` of the command (its directory is tools/)
 * @param {string[]} argv
 * @param {OutputKey} [only]  a per-file command writes only its own output (after compiling the whole set)
 * @returns {number}
 */
export function runCompileCli(moduleUrl, argv, only) {
  const toolsDir = dirname(fileURLToPath(moduleUrl));
  try {
    const args = parseCompileArgs(argv);
    if (args.help) {
      console.log(USAGE);
      return 0;
    }
    const r = compileToDisk({ toolsDir, source: args.source, out: args.out, label: args.label, allowLegacy: args.allowLegacy, only });
    const f = r.set.fabric;
    const repo = resolve(realpathSync.native(toolsDir), "..", "..");
    console.log(`compiled ${r.binding.source} (${r.binding.sourceOrigin})`);
    for (const p of r.written) console.log(`     -> ${within(repo, p) ? posix(relative(repo, p)) : basename(p)}`);
    console.log(`  sha256(source, ${r.binding.sourceDigestForm}) = ${r.binding.sourceSha256}  (${r.binding.sourceBytes} bytes)`);
    console.log(`  exact ${r.binding.sourceExactSha256}  git blob ${r.binding.sourceGitBlob}`);
    console.log(`  sha256(working tree, not bound) = ${r.workingTree.sha256}  (${r.workingTree.bytes} bytes)`);
    console.log(`  devices=${f.devices.length} (inventoried=${f.coverage.devicesInventoried}, topology-only=${f.coverage.devicesOnTopologyOnly})`);
    console.log(`  links=${f.links.length}  findings=${f.findings.length}  crossLayer=${f.crossLayer.length}`);
    for (const w of r.warnings) console.log(`  warning ${w.code}: ${w.message}`);
    return 0;
  } catch (e) {
    if (e instanceof CompileError) {
      console.error(`compile refused — ${e.message}`);
      return USAGE_CODES.has(e.code) ? 2 : 1;
    }
    throw e;
  }
}
