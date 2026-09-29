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
 *   - --out anywhere inside src/ — this package's, or the package's src/ in any other work tree of the
 *     repository — is REFUSED (E_OUT_REFUSED), whatever the source: the tracked files are reached only by
 *     the default sample run;
 *   - for any source other than the sample, --out may be ONLY atlas-scope/.local-data/ (or below it) or a
 *     directory OUTSIDE the repository; every other in-repository location is REFUSED (E_OUT_REFUSED),
 *     Git-ignored or not. The class is "anywhere in the repository a file can be committed, bundled or
 *     served" — dist/ (Vite's outDir, which AssessHub serves without its API guard at /scope and the
 *     portable build ships), public/, review/, node_modules/, src/, docs/, the package root — and it is
 *     named by the one allowed place rather than by a list of forbidden ones: "Git ignores it" says a file
 *     will not be COMMITTED, never that it will not be PUBLISHED (refuter X2, verifier S1-R2V-2). Where
 *     Git owns the tree, .local-data/ must itself be Git-ignored, or a client compile there is refused too;
 *     and it must be a directory OF ITS OWN (`aliasOf`): a .local-data that is a junction, a symbolic link or
 *     a mount names another place under a private-sounding name, and is refused (verifier R3-V2R-2).
 *     Outside the repository the caller owns the location.
 * "THE REPOSITORY" is every work tree of this Git repository — the main checkout and every linked
 *   worktree (`git worktree list`), plus its common Git directory — not only the checkout this command runs
 *   from: from a linked worktree, another checkout's dist/ is served and bundled exactly like this one's
 *   (verifier R3-V2). Where Git does not own the tree, it is the package's parent directory.
 * CONTAINMENT is decided by FILE IDENTITY, not by spelling (verifier R3-V1): a destination is inside a
 * directory when that directory's volume + file index (`stat` dev/ino) is the identity of the destination
 * or of one of its existing ancestors. Text was not enough: `\\localhost\c$\…\src\data` (an admin share
 * loopback), `\\127.0.0.1\…`, `\\?\UNC\…`, a `\\?\Volume{…}` path or a Linux bind mount is a SECOND NAME
 * for the same directory that realpath does not collapse, so a path-text rule called src/data "outside the
 * repository" and wrote client data over the tracked model. Every existing ancestor of the destination must
 * have a readable identity, or the destination is refused (it cannot be placed). The whole-segment text
 * rule is kept alongside ("src/..data" is inside src/) for the part of the path that does not exist yet,
 * and a path component ending in a dot or a space is refused outright: Win32 drops them, so "src./data"
 * can name src/data to one API and a new directory to another.
 * THE TRACKED SET is compiled only from the committed form of the sample: when the default run would
 * write the four tracked files, a sample whose bytes are not already LF-normalised (a CRLF checkout) is
 * refused (E_TRACKED_SOURCE_FORM), because the byte-dependent sourceExactSha256 would then record the
 * checkout's line endings in committed files and the tracked set would differ per clone (verifier R3-V4).
 * Compiling that checkout elsewhere with --out is allowed.
 *
 * WHICH ORIGIN — "repository-file" is a file GIT TRACKS in this repository (named by its repository
 * path); any other file — including an untracked or ignored one inside the repository — is an
 * "external-file", named by its file name. Either way sourceExactSha256 is taken over the bytes as read. Where Git does not own the tree at all (a copied package, a sandbox) there is no tracked/untracked
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
import { existsSync, lstatSync, mkdirSync, mkdtempSync, readFileSync, realpathSync, renameSync, rmSync, statSync, writeFileSync } from "node:fs";
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
                   the sample, only .local-data/ or a directory outside the repository
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
 * A path's identity — its volume and file index as the OS reports them — or null when it cannot be read
 * (absent, unreadable, or a file system that reports no file index). Two spellings of one directory
 * (`C:\r\src`, `\\localhost\c$\r\src`, `\\?\Volume{…}\r\src`) have ONE identity.
 * @param {string} p
 */
function identityOf(p) {
  try {
    const s = statSync(p, { bigint: true });
    return s.ino === 0n ? null : `${s.dev}:${s.ino}`;
  } catch {
    return null;
  }
}

/**
 * Where a canonical destination is, as a predicate `inside(dir)`: true when `dir` is the destination or one
 * of its ancestors — by identity for every existing ancestor, and by whole path segments for the part that
 * does not exist yet. Refuses (E_OUT_REFUSED) a destination one of whose existing ancestors has no readable
 * identity: such a destination cannot be placed, so it is not written.
 * @param {string} canon  canonical destination (see canonicalPath)
 * @param {string} given  the destination as the caller spelled it (named in a refusal)
 * @returns {(dir: string) => boolean}
 */
function placeOf(canon, given) {
  /* Every existing ancestor of the destination, by identity, with the path segments BELOW it that lead to the
     destination (a destination that does not exist yet has a tail of segments still to be created). */
  let cur = canon;
  /** @type {string[]} */
  let tail = [];
  while (!existsSync(cur) && dirname(cur) !== cur) {
    tail = [basename(cur), ...tail];
    cur = dirname(cur);
  }
  /** @type {Map<string, string[]>} identity -> segments from that ancestor down to the destination */
  const chain = new Map();
  for (;;) {
    const id = identityOf(cur);
    if (id === null) {
      throw new CompileError(
        "E_OUT_REFUSED",
        `--out ${given} cannot be placed: the file system does not report an identity for its ancestor ${basename(cur) || cur}, ` +
          `so whether it is inside the repository cannot be decided. Compile to .local-data/ (the default) or to another directory.`,
      );
    }
    if (!chain.has(id)) chain.set(id, tail);
    const up = dirname(cur);
    if (up === cur) break;
    tail = [basename(cur), ...tail];
    cur = up;
  }
  /* Segment comparison for the part that does not exist yet: case-insensitive on Windows, where "SRC" and
     "src" would be created as one directory. */
  const same = process.platform === "win32" ? (/** @type {string} */ a, /** @type {string} */ b) => a.toLowerCase() === b.toLowerCase() : (/** @type {string} */ a, /** @type {string} */ b) => a === b;
  return (dir) => {
    if (within(dir, canon)) return true;
    /* `dir` itself may not exist yet (a fresh .local-data/): place its nearest existing ancestor by identity,
       then require the destination's remaining segments to begin with dir's. */
    let anchor = resolve(dir);
    /** @type {string[]} */
    let rest = [];
    while (!existsSync(anchor) && dirname(anchor) !== anchor) {
      rest = [basename(anchor), ...rest];
      anchor = dirname(anchor);
    }
    const id = identityOf(anchor);
    const below = id === null ? undefined : chain.get(id);
    return below !== undefined && rest.length <= below.length && rest.every((s, i) => same(s, /** @type {string} */ (below[i])));
  };
}

/**
 * Why `dir` (the package's .local-data/, a direct child of the canonical package directory) is NOT a
 * directory of its own — or null when it is, or when it does not exist yet (it is then created as a plain
 * directory). A second name for another place is refused however it is made:
 *   - a symbolic link or a junction (Node's lstat reports a Windows junction or mount point as a link);
 *   - a path the OS resolves elsewhere (its real path is not its own spelling — a link Node cannot see);
 *   - a mount point (a Linux bind mount keeps the directory's own path, so realpath cannot see it; the
 *     kernel's mount table can).
 * @param {string} dir  absolute, under a canonical parent
 * @returns {string | null}
 */
function aliasOf(dir) {
  let st;
  try {
    st = lstatSync(dir);
  } catch {
    return null;
  }
  if (st.isSymbolicLink()) return "it is a symbolic link or a junction";
  if (!st.isDirectory()) return "it is not a directory";
  let real;
  try {
    real = realpathSync.native(dir);
  } catch (e) {
    return `its real path cannot be read (${e instanceof Error ? e.message : String(e)})`;
  }
  const same = process.platform === "win32" ? real.toLowerCase() === dir.toLowerCase() : real === dir;
  if (!same) return "the file system resolves it to another directory";
  if (process.platform === "linux") {
    let table = "";
    try {
      table = readFileSync("/proc/self/mountinfo", "utf8");
    } catch {
      table = "";
    }
    /* Field 5 of each line is the mount point, with space, tab, newline and backslash octal-escaped. */
    const points = table
      .split("\n")
      .map((l) => l.split(" ")[4])
      .filter((p) => p !== undefined)
      .map((p) => p.replace(/\\([0-7]{3})/g, (_m, o) => String.fromCharCode(Number.parseInt(o, 8))));
    if (points.includes(real)) return "it is a mount point";
  }
  return null;
}

/**
 * What Git says about this repository — or null where Git does not own it (no Git, not a work tree, or a
 * work tree whose top level is not this repository, e.g. a sandbox copy under a directory that is one).
 * @param {string} repo  canonical repository root
 */
function gitContext(repo) {
  /** @param {string} cwd @param {string[]} args */
  const gitIn = (cwd, args) => spawnSync("git", ["-C", cwd, ...args], { encoding: "utf8", stdio: ["ignore", "pipe", "pipe"], windowsHide: true });
  /** @param {string[]} args */
  const git = (args) => gitIn(repo, args);
  const top = git(["rev-parse", "--show-toplevel"]);
  if (top.error || top.status !== 0) return null;
  const topDir = top.stdout.trim();
  if (topDir === "" || !existsSync(topDir) || relative(realpathSync.native(topDir), repo) !== "") return null;
  /** The common Git directory of the repository `cwd` belongs to, absolute — or null outside any. @param {string} cwd */
  const commonDirOf = (cwd) => {
    const r = gitIn(cwd, ["rev-parse", "--path-format=absolute", "--git-common-dir"]);
    const d = r.error || r.status !== 0 ? "" : r.stdout.trim();
    return d === "" ? null : resolve(d);
  };
  const commonDir = commonDirOf(repo);
  if (commonDir === null) return null;
  const listed = git(["worktree", "list", "--porcelain"]);
  if (listed.error || listed.status !== 0) {
    throw new CompileError("E_OUT_REFUSED", `git could not list this repository's work trees (${listed.stderr.trim()}), so an --out cannot be placed.`);
  }
  const worktrees = listed.stdout
    .split(/\r?\n/)
    .filter((l) => l.startsWith("worktree "))
    .map((l) => resolve(l.slice("worktree ".length)));
  return {
    /** Whether Git tracks the repository-relative POSIX path `rel`. @param {string} rel */
    tracked: (rel) => git(["ls-files", "--error-unmatch", "--", rel]).status === 0,
    /** Whether Git ignores the repository-relative directory `rel` (which need not exist). @param {string} rel */
    ignoredDir: (rel) => rel !== "" && git(["check-ignore", "-q", "--", `${rel}/`]).status === 0,
    /** Every work tree of this repository (this one included) and its common Git directory. */
    roots: [...new Set([repo, ...worktrees, commonDir])],
    /**
     * Whether the existing directory `dir` belongs to a work tree of THIS repository, whatever it is listed as:
     * Git is asked from inside it, and its common Git directory is compared by identity with ours.
     * @param {string} dir
     */
    sameRepository: (dir) => {
      const theirs = commonDirOf(dir);
      if (theirs === null) return false;
      const a = identityOf(theirs);
      return a !== null && a === identityOf(commonDir);
    },
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
  /** Whether the destination is inside `dir` (by identity; see the header). Only set with --out. */
  let inside = (/** @type {string} */ _dir) => false;
  if (o.out !== undefined) {
    outDir = canonicalPath(o.out, "--out");
    inside = placeOf(outDir, o.out);
    /* Every work tree of the repository (see the header, "THE REPOSITORY"), and the package's src/ in each. */
    const roots = git === null ? [repo] : git.roots;
    const pkgRel = relative(repo, pkg);
    const srcDirs = roots.map((r) => join(r, pkgRel, "src"));
    if (srcDirs.some(inside)) {
      throw new CompileError(
        "E_OUT_REFUSED",
        `--out ${o.out} is inside ${posix(relative(repo, srcDir))}/ (of this or another work tree of the repository), whose compiled ` +
          `files are tracked in Git. The tracked files are written only by the default sample run; compile anything else to a ` +
          `directory outside src/ (default: .local-data/).`,
      );
    }
    /* The one in-repository place a client compile may go is THIS package's .local-data/. Anything else inside a
       work tree of the repository — by identity, or because Git run from inside it names our common directory —
       is refused. The nearest existing ancestor is what Git is asked about (the destination may not exist yet). */
    let probe = outDir;
    while (!existsSync(probe) && dirname(probe) !== probe) probe = dirname(probe);
    const inRepository = roots.some(inside) || (git !== null && git.sameRepository(probe));
    if (!isSample && inRepository && !inside(localData)) {
      throw new CompileError(
        "E_OUT_REFUSED",
        `--out ${o.out} is inside the repository and is not ${posix(relative(repo, localData))}/: a compiled assessment anywhere else ` +
          `in the repository is one \`git add\`, one build or one served directory away from publishing client data — dist/ ` +
          `(served at /scope and bundled onto the portable stick), public/, review/, node_modules/ and src/ included, Git-ignored or ` +
          `not (ignored says "not committed", never "not published"). Compile it to ${posix(relative(repo, localData))}/ (the default) ` +
          `or to a directory outside the repository.`,
      );
    }
  }
  /* The one in-repository destination a client compile may use is itself CHECKED, not assumed: where Git owns
     the tree, .local-data/ must be one Git ignores, or the default run would leave the model one `git add`
     from the history. */
  const landsInLocalData = !isSample && (outDir === undefined || inside(localData));
  /* ...and it is placed by IDENTITY, not by its name (verifier R3-V2R-2): a .local-data that is a junction, a
     symbolic link or a mount is a second name for another directory — src/data (whose fabric.json is tracked),
     dist/ (served at /scope) or anywhere else — and "Git ignores .local-data/" says nothing about that place. */
  if (landsInLocalData) {
    const why = aliasOf(localData);
    if (why !== null) {
      throw new CompileError(
        "E_OUT_REFUSED",
        `${posix(relative(repo, localData))}/ is not a directory of its own: ${why}. A client compile there would land in whatever ` +
          `it names — src/data, dist/ or anywhere else — under a name that says it is private. Make ${posix(relative(repo, localData))}/ ` +
          `a plain directory, or compile to a directory outside the repository with --out. Nothing was written.`,
      );
    }
  }
  if (landsInLocalData && git !== null && !git.ignoredDir(posix(relative(repo, localData)))) {
    throw new CompileError(
      "E_OUT_REFUSED",
      `${posix(relative(repo, localData))}/ is not ignored by Git in this repository, so a client compile there could be committed. ` +
        `Restore its .gitignore entry, or compile to a directory outside the repository with --out.`,
    );
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
  /* The TRACKED set is compiled from the committed form only (see the header, THE TRACKED SET): the bytes as
     read must already be LF-normalised, so the one byte-dependent key equals the committed form's digest. */
  const writesTracked = isSample && outDir === undefined;
  if (writesTracked && binding.sourceExactSha256 !== `sha256:${binding.sourceSha256}`) {
    throw new CompileError(
      "E_TRACKED_SOURCE_FORM",
      `${repoRel} on disk is not in its committed (LF) form — this checkout renders it with CRLF line endings — so the ` +
        `tracked compiled files would record this checkout's bytes (sourceExactSha256 ${binding.sourceExactSha256.slice(0, 19)}…, ` +
        `committed form sha256:${binding.sourceSha256.slice(0, 12)}…) and differ from every other clone's. Check the sample out ` +
        `with LF line endings (an eol=lf attribute for it, or core.autocrlf=false, then a fresh checkout of that one file), ` +
        `or compile this checkout elsewhere with --out. Nothing was written.`,
    );
  }
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
