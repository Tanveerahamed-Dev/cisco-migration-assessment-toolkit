/**
 * source-hygiene.test.ts — properties every file in this repository must have, enforced rather
 * than hoped for.
 *
 * This exists because of a defect that recurred THREE times across three independently-written
 * modules: `src/analysis/blast.ts`, `src/panels/PriorityQueue.tsx` and `src/panels/JsonView.tsx`
 * each contained literal NUL bytes, used as a composite-key separator in a template string with
 * the character typed directly into the source instead of written as a six-character escape.
 *
 * (This file made the same mistake on its first draft: the sentence above originally spelled the
 * escape out, and the editor helpfully turned it into a real NUL — so the NUL detector shipped
 * containing a NUL. The gate caught its own author within a minute of being written, which is
 * about the best argument for it there is. Nothing below embeds a control character; the two that
 * are needed are constructed from their code points.)
 *
 * It compiles, it runs, and every test passes — so nothing in the normal pipeline objects. What it
 * breaks is the review tooling: `git diff`, `grep`, `file(1)` and most editors classify a file
 * containing a NUL as BINARY. `grep -rn "thing" src/` silently skips it. A 1,000-line module can
 * drop out of every code search in the project without one error message, and it is invisible
 * precisely to the people looking for it.
 *
 * ── WHY THE WALK STARTS AT THE REPOSITORY ROOT ──────────────────────────────────────────────────
 *
 * It used to start at `src/` and accept four extensions, and that scope was wrong in the way this
 * whole class of gate tends to be wrong: it covered the place the bug had been found rather than
 * the place the bug can occur. Measured 2026-09-21 — `docs/open-issues.md`, the document that
 * DESCRIBES this bug class, contained two live NUL bytes. `file(1)` called it `data`; grep called
 * it `Binary file ... matches`; the gate could not see it at all, because it is neither in `src/`
 * nor one of the four extensions. `tools/*.mjs` and `review/*.mjs` were outside it for the same
 * reason, and they are the scripts that build the shipped data and the review evidence.
 *
 * The property has nothing to do with being a TypeScript file under `src/`: it is that every file
 * a human is expected to read, diff or grep stays readable, diffable and greppable. So the walk is
 * the repository, minus the directories that hold generated or third-party bytes, and the
 * extension list is "text formats this project authors".
 */
import { execFileSync, spawnSync } from "node:child_process";
import { existsSync, mkdtempSync, readdirSync, readFileSync, rmSync, statSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { basename, dirname, extname, join, relative, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";
import ts from "typescript";
import { beforeAll, describe, expect, it } from "vitest";

const SRC = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const ROOT = resolve(SRC, "..");

/**
 * Directories holding bytes nobody authors by hand. `review/shots`, `review/blind` and
 * `review/reports` are regenerated screenshot and measurement output (and are gitignored for the
 * same reason); `.audit` is scratch written by review agents. Everything else is in scope.
 */
const SKIP_DIRS = new Set(["node_modules", "dist", ".git", ".vite", ".audit", "shots", "blind", "reports"]);

/** Text formats this project authors. A PNG is allowed to contain a NUL; a Markdown file is not. */
const TEXT_EXTENSIONS = new Set([
  ".ts",
  ".tsx",
  ".js",
  ".mjs",
  ".cjs",
  ".css",
  ".json",
  ".md",
  ".html",
  ".txt",
  ".yml",
  ".yaml",
  ".svg",
]);

/** Authored text files that carry no extension at all. */
const TEXT_NAMES = new Set([".gitignore", ".npmrc", ".editorconfig"]);

function walk(dir: string, out: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) {
      if (SKIP_DIRS.has(name)) continue;
      walk(p, out);
    } else if (TEXT_EXTENSIONS.has(extname(p)) || TEXT_NAMES.has(name)) {
      out.push(p);
    }
  }
  return out;
}

/* Constructed, never embedded: a file that hunts control characters must not contain one. */
const REPLACEMENT_CHAR = String.fromCharCode(0xfffd);

/**
 * WHAT THE BYTE SCANS READ: the files Git calls part of the tree — tracked, plus untracked files no
 * ignore rule claims (an authored file not yet added is in scope; declared scratch is not).
 *
 * It was `walk(ROOT)` minus SKIP_DIRS, and that scope was set by the directories that happened to
 * exist rather than by the property. Git-ignored scratch kept appearing under names the list did not
 * hold — `.local-data/` (other agents' builds, captures and compiled snapshots), `dist-hub/` — so the
 * scans read them. Measured by acceptance F2's re-grade: 1,398 files / 130.2 MB read, of
 * which 408 files / 10.7 MB were tracked; the NUL test took 0.9 s, 5.8 s and 70.6 s on three runs as
 * that scratch grew, and timed out at 30 s once — a verdict that measured other agents' leftovers,
 * and a NUL in a scratch file nobody diffs would have turned the product suite red. Being ignored is
 * the declaration that a file is not authored here (.gitignore says so in as many words), so Git's
 * own answer is the denominator: it moves with .gitignore, never with a hand-kept list.
 *
 * Outside a Git checkout there is no such answer. The run then fails (see "finds files to check")
 * unless ATLAS_SCOPE_NO_GIT=1 acknowledges it, in which case the old directory walk stands in.
 */
function authoredTextFiles(): { files: string[]; gitError: string | null } {
  let listed: string;
  try {
    listed = execFileSync("git", ["ls-files", "--cached", "--others", "--exclude-standard", "-z"], {
      cwd: ROOT,
      encoding: "utf8",
      maxBuffer: 64 * 1024 * 1024,
      stdio: ["ignore", "pipe", "pipe"],
    });
  } catch (e) {
    return { files: process.env.ATLAS_SCOPE_NO_GIT === "1" ? walk(ROOT) : [], gitError: String(e).slice(0, 300) };
  }
  const files = listed
    .split("\0")
    .filter((r) => r.length > 0 && (TEXT_EXTENSIONS.has(extname(r)) || TEXT_NAMES.has(basename(r))))
    .map((r) => resolve(ROOT, r))
    /* A tracked file deleted in the working tree is listed by `--cached` and has no bytes to read. */
    .filter((f) => existsSync(f));
  return { files, gitError: null };
}

const authored = authoredTextFiles();
const files = authored.files;
/**
 * What the runner collects and the build executes, ignored by Git or not: `src/` and `tools/`,
 * walked. The gates below that ask "will this RUN?" read this set, because vitest's glob does not
 * consult .gitignore — a probe parked in an ignored path under `src/` still runs.
 */
const runnable = [...walk(SRC), ...walk(resolve(ROOT, "tools"))];
const rel = (f: string): string => relative(ROOT, f).split("\\").join("/");

/** Each file among `paths` holding a byte for which `bad` is true, with the count — the NUL scan's detector. */
function byteOffenders(paths: readonly string[], bad: (b: number) => boolean): string[] {
  const out: string[] = [];
  for (const f of paths) {
    let count = 0;
    for (const b of readFileSync(f)) if (bad(b)) count++;
    if (count > 0) out.push(`${rel(f)} — ${count} NUL byte(s)`);
  }
  return out;
}
const isNul = (b: number): boolean => b === 0;

describe("authored files stay text", () => {
  it("finds files to check — an empty scan is not a pass", () => {
    if (authored.gitError !== null) {
      expect(
        process.env.ATLAS_SCOPE_NO_GIT,
        `git could not list the authored files (${authored.gitError}); set ATLAS_SCOPE_NO_GIT=1 to acknowledge ` +
          "that this run scanned a directory walk instead",
      ).toBe("1");
    }
    expect(files.length).toBeGreaterThan(60);
  });

  it("covers the directories outside src/ that a narrower walk missed", () => {
    /* The scope IS the assertion here. This gate reported green over a NUL-bearing document for as
       long as it looked only at `src/`, so the denominator gets pinned rather than assumed. */
    const dirs = new Set(files.map((f) => rel(f).split("/")[0]));
    for (const d of ["src", "docs", "tools", "review"]) {
      expect(dirs.has(d), `${d}/ is not being scanned`).toBe(true);
    }
    expect(files.some((f) => rel(f) === "docs/open-issues.md")).toBe(true);
    expect(files.some((f) => rel(f) === "tools/compile-snapshot.mjs")).toBe(true);
    expect(files.some((f) => rel(f) === "review/capture.mjs")).toBe(true);
  });

  it("reads what Git calls authored, and no Git-ignored scratch", () => {
    /* Asked of Git independently of how the list was made: `check-ignore` names every path among
       them that an ignore rule claims (a tracked path is never reported). Red on the old walk, which
       read the builds and captures under `.local-data/` — 18 of them in the run that wrote this. */
    if (authored.gitError !== null) {
      expect(process.env.ATLAS_SCOPE_NO_GIT).toBe("1");
      return;
    }
    const asked = spawnSync("git", ["check-ignore", "--stdin", "-z"], {
      cwd: ROOT,
      input: files.map(rel).join("\0"),
      encoding: "utf8",
      maxBuffer: 64 * 1024 * 1024,
    });
    /* Exit 0: at least one path is ignored (they are printed); 1: none is; anything else: Git failed. */
    expect([0, 1], `git check-ignore failed: ${asked.stderr ?? String(asked.error)}`).toContain(asked.status);
    const ignored = asked.stdout.split("\0").filter((r) => r.length > 0);
    expect(ignored.slice(0, 10), `${ignored.length} Git-ignored file(s) in the byte scans`).toEqual([]);
  });

  it("contains no literal NUL byte", () => {
    const offenders = byteOffenders(files, isNul);
    expect(
      offenders,
      `these files contain literal NUL bytes and will be treated as BINARY by git, grep and most\n` +
        `editors — write the six-character escape instead, which is byte-identical at runtime:\n` +
        offenders.join("\n"),
    ).toEqual([]);
  });

  it("contains no other C0 control character except tab, newline and carriage return", () => {
    // The same reasoning as above, one step wider: any stray control byte can confuse a diff or a
    // terminal. Tab/LF/CR are legitimate; nothing else in this range is.
    const offenders: string[] = [];
    for (const f of files) {
      const buf = readFileSync(f);
      const bad = new Map<number, number>();
      for (const b of buf) {
        if (b < 0x20 && b !== 0x09 && b !== 0x0a && b !== 0x0d) bad.set(b, (bad.get(b) ?? 0) + 1);
      }
      if (bad.size > 0) {
        const detail = [...bad].map(([code, n]) => `0x${code.toString(16).padStart(2, "0")}×${n}`).join(", ");
        offenders.push(`${rel(f)} — ${detail}`);
      }
    }
    expect(offenders, `stray control characters:\n${offenders.join("\n")}`).toEqual([]);
  });

  it("is valid UTF-8 that round-trips unchanged", () => {
    // A replacement character means bytes were already lost somewhere upstream; catching it here
    // beats discovering it in rendered prose.
    const offenders: string[] = [];
    for (const f of files) {
      const buf = readFileSync(f);
      const text = buf.toString("utf8");
      if (!Buffer.from(text, "utf8").equals(buf)) offenders.push(`${rel(f)} — not valid UTF-8`);
      else if (text.includes(REPLACEMENT_CHAR)) offenders.push(`${rel(f)} — contains U+FFFD`);
    }
    expect(offenders, `encoding damage:\n${offenders.join("\n")}`).toEqual([]);
  });

  it("the gate is live — it detects a planted NUL", () => {
    /* Proves the detector the scan USES fires, on a real file: this used to count NULs in a buffer
       with a loop of its own, which proved that loop, not the gate. A clean twin is the control.
       Planted outside the tree, so the run writes nothing a scan or a commit can pick up. */
    const dir = mkdtempSync(join(tmpdir(), "atlas-nul-"));
    try {
      const dirty = join(dir, "planted.ts");
      const clean = join(dir, "clean.ts");
      writeFileSync(dirty, Buffer.from(`const k = \`a${String.fromCharCode(0)}b\`;`, "utf8"));
      writeFileSync(clean, "const k = `a\\u0000b`;\n");
      const found = byteOffenders([dirty, clean], isNul);
      expect(found).toHaveLength(1);
      expect(found[0]).toMatch(/planted\.ts — 1 NUL byte\(s\)$/);
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });

  it("leaves no scratch, probe or temporary file where the build or the test glob will find it", () => {
    /* Refuters and build agents write diagnostic probes. Several have leaked into `src/` during
       this build, and because the test glob is `src/**` they then RUN — one was a bare
       `it("probe")` with no assertion at all, inflating the pass count while proving nothing; a
       later one wrote to an absolute Temp path from inside the suite and turned `vitest run` red
       for everyone.

       SCOPE, stated rather than implied: `src/` and `tools/` — the directories whose contents the
       test glob runs and the build executes. `review/` is deliberately NOT included: it is where
       hand-run review instruments live by design (`probe-fabric.mjs` is one of them and is named
       for what it does), and nothing there is imported by the app or collected by vitest. Scratch
       parked in a gitignored directory is likewise out of scope — being gitignored is the
       declaration that it is not part of the tree.

       THIS IS THE CHEAP NET, NOT THE GATE. It matches NAMES, and a name match is a convention, not
       a proof. It was the whole gate once and it did not hold: the regex requires the trailing
       underscore in `zz_`, so six `src/zzaudit*.test.ts` files — every one of them a bare `it()`
       with zero assertions, every one of them counted as a PASS — sat in `src/` while this test was
       green. The structural check below is the one that closes the class; this one stays because it
       is free and it catches a leftover the moment it lands, before anyone runs it. */
    const watched = runnable.filter((f) => {
      const r = rel(f);
      return r.startsWith("src/") || r.startsWith("tools/");
    });
    expect(watched.length, "the scratch walk found nothing to watch").toBeGreaterThan(20);
    const junk = watched
      .map(rel)
      /* Widened where it missed, and only there. `zz_` → `zz` (it read `zzaudit` as clean because
         of one absent underscore); `tmp_` → `tmp`; and a leading run of `_` or `.` is skipped
         before matching, because `src/_tmp/` is the same word wearing a different prefix and the
         first version of this widening walked straight past it too. Deliberately NOT widened to
         words a real module could legitimately carry (`audit`, `check`, `sandbox`) — this net is
         allowed to be cheap, it is not allowed to block honest names, and the structural gate below
         is what actually closes the class. */
      .filter((f) => /(^|[\\/])[_.]*(__|zz|tmp|scratch|probe|dump)/i.test(f));
    expect(junk, `scratch files left where they will run:\n${junk.join("\n")}`).toEqual([]);
  });
});

/* ────────────────────────────────────────────────────────────────────────────────────────────────
 * Every test the runner collects must actually assert something.
 *
 * WHY THIS EXISTS, and why it is not another name list. The gate above was written after one
 * leftover (`src/forwarding/zz_scratch.test.ts`) and was scoped to that file's NAME. Six files
 * later named `zzaudit*.test.ts` — no underscore — walked straight past it. Each contained a bare
 * `it()` with zero assertions; vitest collected them, reported them as PASSED, and the pass count
 * went from 737 to 742 without one additional thing being proven. A green suite that grows by five
 * tests which assert nothing is worse than a red one, because it reads as progress.
 *
 * The property the old comment already NAMED — "a bare it(\"probe\") with no assertion at all,
 * inflating the pass count while proving nothing" — is the property that is checked here. It
 * catches `check.ts`, it catches `zzaudit.test.ts`, and it catches the file nobody has named yet.
 *
 * WHAT IT CANNOT DO, stated rather than implied:
 *   - It matches test calls in text, but the text it reads is made by the TypeScript parser:
 *     comments and the contents of string, template, regex and JSX-text literals are removed first,
 *     so prose and fixtures cannot satisfy or break it. (It used a hand lexer until 2026-09-27; that
 *     read a quote or a `/*` inside a regex literal as the start of a string or comment and swallowed
 *     the code after it — hiding whole tests, silently, not only the loud false positive this note
 *     used to promise. The act tripwire below had the same defect, verifier finding F2-V1.)
 *   - `it.each(...)(...)` is handled (the last call group in the chain is the definition call), but
 *     a test whose callback is a bare identifier defined in another MODULE cannot be followed, and
 *     is accepted. Helpers defined in the SAME file are followed to a fixpoint.
 *   - It says nothing about whether the assertions are GOOD. `expect(true).toBe(true)` passes this.
 *     Absence of assertion is the only thing it can see, and it is the thing that recurred.
 * ──────────────────────────────────────────────────────────────────────────────────────────────── */

/**
 * The source with comments removed and the CONTENTS of string, template, regex and JSX-text literals
 * replaced by `""`; template `${}` holes are kept, because a hole is code. Tokens are read by the
 * TypeScript parser, not by a hand lexer: a hand lexer cannot tell a regex literal from division, so
 * a quote or a comment opener inside `/'s IP$/` swallowed the code after it (a test that asserts
 * nothing, hidden). Token text is copied exactly; the trivia between tokens collapses to one space,
 * or one newline where it held a line break.
 */
function stripNoise(src: string, name = "planted.ts"): string {
  const sf = ts.createSourceFile(name, src, ts.ScriptTarget.Latest, true, /x$/.test(name) ? ts.ScriptKind.TSX : ts.ScriptKind.TS);
  let out = "";
  let at = 0;
  const token = (node: ts.Node): void => {
    const start = node.getStart(sf);
    const gap = src.slice(at, start);
    if (gap !== "") out += gap.includes("\n") ? "\n" : " ";
    at = node.getEnd();
    switch (node.kind) {
      case ts.SyntaxKind.StringLiteral:
      case ts.SyntaxKind.NoSubstitutionTemplateLiteral:
      case ts.SyntaxKind.TemplateHead:
      case ts.SyntaxKind.RegularExpressionLiteral:
      case ts.SyntaxKind.JsxText:
        out += '""';
        break;
      case ts.SyntaxKind.TemplateMiddle:
      case ts.SyntaxKind.TemplateTail:
        out += " ";
        break;
      default:
        out += src.slice(start, at);
    }
  };
  const walk = (node: ts.Node): void => {
    if (node.kind >= ts.SyntaxKind.FirstJSDocNode && node.kind <= ts.SyntaxKind.LastJSDocNode) return;
    const kids = node.getChildren(sf);
    if (kids.length > 0) for (const k of kids) walk(k);
    else if (node.kind !== ts.SyntaxKind.SyntaxList && node.kind !== ts.SyntaxKind.EndOfFileToken) token(node);
  };
  walk(sf);
  return out;
}

/** The span of the balanced `(...)` starting at `open`, or null if it never closes. */
function balanced(src: string, open: number): { start: number; end: number } | null {
  let depth = 0;
  for (let i = open; i < src.length; i++) {
    const c = src[i];
    if (c === "(") depth++;
    else if (c === ")") {
      depth--;
      if (depth === 0) return { start: open + 1, end: i };
    }
  }
  return null;
}

/** Anything that counts as asserting. Helper names discovered in the file are added per-file. */
const ASSERTION = /\bexpect(?:TypeOf|\.soft)?\s*\(|\bassert\b|\bexpect\.\w/;

/**
 * Every `it(...)`/`test(...)` definition in one file, with the source text of its callback body.
 * `body === null` means the call had no inline function — either `it("name")` (a todo, skipped) or
 * a callback passed by identifier, which is resolved through the helper set instead.
 */
function testDefinitions(stripped: string): { name: string; body: string | null; raw: string }[] {
  const out: { name: string; body: string | null; raw: string }[] = [];
  const head = /(^|[^.\w$])(it|test)(?![\w$])/g;
  let m: RegExpExecArray | null;
  while ((m = head.exec(stripped)) !== null) {
    let i = m.index + (m[1] ?? "").length + (m[2] ?? "").length;
    let last: { start: number; end: number } | null = null;
    /* Consume the whole call chain: `.each(A)("name", fn)` is two groups and the DEFINITION is the
       last one. Taking the first would read `cases.map((d) => d.id)` as the test body. */
    for (;;) {
      while (i < stripped.length && /\s/.test(stripped[i] as string)) i++;
      if (stripped[i] === ".") {
        i++;
        while (i < stripped.length && /[\w$]/.test(stripped[i] as string)) i++;
        continue;
      }
      if (stripped[i] === "(") {
        const span = balanced(stripped, i);
        if (span === null) break;
        last = span;
        i = span.end + 1;
        continue;
      }
      break;
    }
    if (last === null) continue;
    const args = stripped.slice(last.start, last.end);
    const fn = args.search(/=>|\bfunction\b/);
    out.push({
      name: `${stripped.slice(Math.max(0, m.index), m.index + 60).replace(/\s+/g, " ")}…`,
      body: fn === -1 ? null : args.slice(fn),
      raw: args,
    });
  }
  return out;
}

/** Identifiers declared in this file whose own body asserts, followed to a fixpoint. */
function assertingHelpers(stripped: string, name = "planted.ts"): Set<string> {
  const names = new Set<string>();
  /* Each helper's own body, read from the parse of the stripped text: a function declaration, a method,
     or a variable bound to an arrow or function expression. (A text search for the first `{` after the
     name read a typed parameter's `{ … }` as the body, and read whatever block followed a plain
     `const x = 1;` as x's body — see the liveness case below.) */
  const decls: { name: string; body: string }[] = [];
  const sf = ts.createSourceFile(name, stripped, ts.ScriptTarget.Latest, true, /x$/.test(name) ? ts.ScriptKind.TSX : ts.ScriptKind.TS);
  const visit = (n: ts.Node): void => {
    if ((ts.isFunctionDeclaration(n) || ts.isMethodDeclaration(n)) && n.name !== undefined && ts.isIdentifier(n.name) && n.body !== undefined) {
      decls.push({ name: n.name.text, body: n.body.getText(sf) });
    }
    if ((ts.isVariableDeclaration(n) || ts.isPropertyAssignment(n)) && ts.isIdentifier(n.name) && n.initializer !== undefined) {
      let init: ts.Expression = n.initializer;
      while (ts.isParenthesizedExpression(init) || ts.isAsExpression(init) || ts.isSatisfiesExpression(init)) init = init.expression;
      if (ts.isArrowFunction(init) || ts.isFunctionExpression(init)) decls.push({ name: n.name.text, body: init.body.getText(sf) });
    }
    ts.forEachChild(n, visit);
  };
  visit(sf);
  let grew = true;
  while (grew) {
    grew = false;
    for (const d of decls) {
      if (names.has(d.name)) continue;
      const usesHelper = [...names].some((h) => new RegExp(`\\b${h}\\s*\\(`).test(d.body));
      if (ASSERTION.test(d.body) || usesHelper) {
        names.add(d.name);
        grew = true;
      }
    }
  }
  return names;
}

/** Each test in one file's source that asserts nothing, directly or through a helper of the file, by its label. */
function assertionFree(text: string, name: string): string[] {
  const stripped = stripNoise(text, name);
  const helpers = assertingHelpers(stripped, name);
  const helperCall = helpers.size === 0 ? null : new RegExp(`\\b(?:${[...helpers].join("|")})\\b`);
  const out: string[] = [];
  for (const t of testDefinitions(stripped)) {
    // `it("name")` with no callback is a vitest TODO, reported as todo and not as a pass.
    if (t.body === null && !/,/.test(t.raw)) continue;
    const body = t.body ?? t.raw;
    if (ASSERTION.test(body)) continue;
    if (helperCall !== null && helperCall.test(body)) continue;
    out.push(t.name);
  }
  return out;
}

describe("every test the runner collects asserts something", () => {
  /* The set this walks must be the set vitest RUNS. Read the runner's own globs and assert they are
     the ones assumed here, so a config change cannot quietly narrow the gate's denominator. */
  const vitestConfig = readFileSync(resolve(ROOT, "vitest.config.ts"), "utf8");

  it("covers exactly the globs the runner collects", () => {
    expect(vitestConfig).toContain(`include: ["src/**/*.test.ts", "src/**/*.test.tsx"]`);
  });

  it("excludes only the underscore scratch class, and that class hides nothing authored", () => {
    /* vitest.config.ts excludes every `src/` path with a segment starting `_`, so a probe an agent
       parks there cannot run as part of the suite. An exclusion is also a way to silence a real
       test, so both halves are pinned: the exclude list is exactly Vitest's defaults plus that one
       class, and no file under `src/` actually carries such a segment — which means the class is
       empty in the authored tree and the exclusion only ever bites scratch. */
    expect(vitestConfig).toContain(`exclude: [...configDefaults.exclude, "src/**/_*/**", "src/**/_*"]`);
    expect(vitestConfig.match(/\bexclude\s*:/g) ?? []).toHaveLength(1);
    const underscored = runnable.map(rel).filter((f) => f.startsWith("src/") && f.split("/").some((seg) => seg.startsWith("_")));
    expect(underscored, `files under src/ the runner now skips:\n${underscored.join("\n")}`).toEqual([]);
  });

  const collected = runnable
    .map(rel)
    .filter((f) => f.startsWith("src/") && (f.endsWith(".test.ts") || f.endsWith(".test.tsx")));

  it("found the suite to walk", () => {
    // A walk that found nothing would pass every check below while proving nothing at all.
    expect(collected.length).toBeGreaterThan(20);
  });

  /* One case per file (vitest.config.ts: a large unit of work is split one record per test). Measured
     2026-09-27: the whole-suite walk took 9.4 s in one case on a 73 %-busy host, a third of the hang
     detector, and a loaded run multiplies that. */
  describe("finds no test with zero assertions", () => {
    it.each(collected)("%s", (f) => {
      const offenders = assertionFree(readFileSync(resolve(ROOT, f), "utf8"), f).map((t) => `${f} — ${t}`);
      expect(
        offenders,
        `tests that run, pass, and assert nothing:\n${offenders.join("\n")}`,
      ).toEqual([]);
    });
  });

  it("the gate reads a helper's own body — not the next block after a name, nor a parameter's type", () => {
    /* Measured 2026-09-27: the helper finder took the first `{` after `function name` or `const name =`
       as the body. For `function expectThing(opts: { a: number })` that is the parameter's TYPE, so a
       real asserting helper was missed; for `const other = 1;` it is whatever block comes next — here an
       asserting test — so every test that merely names `other` read as asserting, and one that asserts
       nothing passed (PriorityQueue.filtered-reveal.test.tsx's severity-chip case passed that way). */
    const text = [
      "async function expectThing(opts: { a: number }): Promise<void> { expect(opts.a).toBe(1); }",
      "const other = 1;",
      'it("asserts directly", () => { expect(other).toBe(1); });',
      'it("asserts through a helper whose parameter is typed", async () => { await expectThing({ a: 1 }); });',
      'it("only names a constant", () => { void other; });',
      "const check = (n: number): void => { expect(n).toBeGreaterThan(0); };",
      'it("asserts through an arrow helper", () => { check(1); });',
    ].join("\n");
    const found = assertionFree(text, "planted.ts");
    expect(found).toHaveLength(1);
    // Labels are read from the stripped text (names blanked), so the case is known by its code.
    expect(found[0]).toMatch(/void other/);
  });

  it("the gate is live — it detects a planted assertion-free test", () => {
    /* A gate whose failure path was never executed is not a gate. Every shape that got past the
       name regex is planted here, including the exact one that did: `it("...", () => { ... })`
       with no assertion, in a file whose NAME matches nothing. */
    const planted = [
      `it("probe", () => { const x = 1 + 1; });`,
      `it("writes somewhere", async () => { await writeFile(tmp, "x"); });`,
      `it.each([1, 2])("case %s", (n) => { console.log(n); });`,
      `test("silent", function () { doSomething(); });`,
    ].join("\n");
    const stripped = stripNoise(planted);
    const found = testDefinitions(stripped);
    expect(found).toHaveLength(4);
    for (const t of found) {
      expect(ASSERTION.test(t.body ?? t.raw), `planted test was read as asserting: ${t.name}`).toBe(false);
    }
  });

  it("the gate does not fire on a test that does assert, directly or through a helper", () => {
    // The other half of live: a detector that flags everything is as useless as one that flags
    // nothing, and this is the shape (`expectRow(...)`) real files in this suite use.
    const honest = [
      `function expectRow(r) { expect(r.id).toBeDefined(); }`,
      `it("direct", () => { expect(1).toBe(1); });`,
      `it("through a helper", () => { expectRow({ id: "a" }); });`,
      `it.each([1])("parameterised %s", (n) => { expect(n).toBe(1); });`,
    ].join("\n");
    const stripped = stripNoise(honest);
    const helpers = assertingHelpers(stripped);
    expect(helpers.has("expectRow")).toBe(true);
    const helperCall = new RegExp(`\\b(?:${[...helpers].join("|")})\\b`);
    const defs = testDefinitions(stripped);
    expect(defs.length).toBeGreaterThanOrEqual(3);
    for (const t of defs) {
      const text = t.body ?? t.raw;
      expect(ASSERTION.test(text) || helperCall.test(text), `false positive on: ${t.name}`).toBe(true);
    }
  });

  it("the gate is not blinded by a regex literal — a quote or a comment opener inside one hides no test", () => {
    /* The act tripwire's F2-V1 defect, in this gate: a text stripper reads the quote in `/'s IP$/` as a
       string opener and swallows code up to the next quote — here an assertion-free test, which then
       passes unseen (a FALSE NEGATIVE, not the loud false positive this gate once claimed was its only
       failure mode). `/\/*x/` opens a fake comment the same way. */
    const planted = [
      "const re = /'s IP address$/;",
      'it("hidden behind a quote in a regex", () => { const x = 1 + 1; });',
      "const re2 = /a\\/*b/;",
      'it("hidden behind a comment opener in a regex", () => { const y = 2; });',
      "const re3 = /\"/;",
      'it("asserts after a regex", () => { expect(re3.test("a")).toBe(false); });',
    ].join("\n");
    const found = testDefinitions(stripNoise(planted));
    expect(found.map((t) => ASSERTION.test(t.body ?? t.raw))).toEqual([false, false, true]);
  });

  it("the gate reads code, not prose — a commented-out expect does not satisfy it", () => {
    const fake = `it("looks fine", () => {\n  // expect(x).toBe(1);\n  const s = "expect(x).toBe(1)";\n});`;
    const stripped = stripNoise(fake);
    const defs = testDefinitions(stripped);
    expect(defs).toHaveLength(1);
    expect(ASSERTION.test(defs[0]?.body ?? "")).toBe(false);
  });
});

/* ── the TypeScript program the two checker-backed gates below read ──────────────────────────────
 * Both gates decide by symbol and type, not by text, so both read one program built from
 * tsconfig.json over every checked source under src/. It is built once, by whichever gate needs it
 * first, and the planted programs their liveness tests build share its parsed files. */

const CODE = /\.(?:[cm]?[jt]s|[jt]sx)$/;
/** What tsconfig.json reads: .ts/.tsx (allowJs is off). */
const CHECKED = /\.tsx?$/;
/* Its own walk, over every JS/TS source under src/: the text walk above collects only the extensions
   this project happens to author today, so a .mts/.cts/.jsx file would slip past it. */
const walkCode = (dir: string, out: string[] = []): string[] => {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) {
      if (!SKIP_DIRS.has(name)) walkCode(p, out);
    } else if (CODE.test(name) && !name.endsWith(".d.ts")) out.push(p);
  }
  return out;
};
const codeFiles = walkCode(SRC).map(rel);
const parseAs = (text: string, name: string): ts.SourceFile =>
  ts.createSourceFile(name, text, ts.ScriptTarget.Latest, true, /x$/.test(name) ? ts.ScriptKind.TSX : ts.ScriptKind.TS);
const appOptions = (): ts.CompilerOptions => {
  const file = resolve(ROOT, "tsconfig.json");
  const raw = ts.readConfigFile(file, (p) => readFileSync(p, "utf8"));
  if (raw.error !== undefined) throw new Error("tsconfig.json could not be read");
  return ts.parseJsonConfigFileContent(raw.config, ts.sys, ROOT, undefined, file).options;
};
const OPTIONS = appOptions();
const PARSED = new Map<string, ts.SourceFile>();
/** A host that parses each file once for every program built here; planted texts are served, never cached. */
const hostWith = (planted: ReadonlyMap<string, string> = new Map()): ts.CompilerHost => {
  const host = ts.createCompilerHost(OPTIONS, true);
  const readFile = host.readFile.bind(host);
  const fileExists = host.fileExists.bind(host);
  const getSourceFile = host.getSourceFile.bind(host);
  host.readFile = (f) => planted.get(resolve(f)) ?? readFile(f);
  host.fileExists = (f) => planted.has(resolve(f)) || fileExists(f);
  /* A planted module in a directory of its own (a mock scenario's ./H) resolves only if its directory "exists". */
  const directoryExists = host.directoryExists?.bind(host);
  host.directoryExists = (d) => [...planted.keys()].some((p) => p.startsWith(`${resolve(d)}${sep}`)) || (directoryExists?.(d) ?? true);
  host.getSourceFile = (fileName, languageVersion, onError, shouldCreate) => {
    const text = planted.get(resolve(fileName));
    if (text !== undefined) return parseAs(text, fileName);
    const hit = PARSED.get(resolve(fileName));
    if (hit !== undefined) return hit;
    const made = getSourceFile(fileName, languageVersion, onError, shouldCreate);
    if (made !== undefined) PARSED.set(resolve(fileName), made);
    return made;
  };
  return host;
};
let tree: ts.Program | undefined;
/** The program over every checked source under src/. */
const treeProgram = (): ts.Program =>
  (tree ??= ts.createProgram(codeFiles.filter((f) => CHECKED.test(f)).map((f) => resolve(ROOT, f)), OPTIONS, hostWith()));
/** One program over planted texts, as virtual files under src/core/ (never written). */
const plantedProgram = (stem: string, texts: string[]): { program: ts.Program; files: ts.SourceFile[] } => {
  const paths = texts.map((_, i) => resolve(SRC, "core", `${stem}-${i}.tsx`));
  const program = ts.createProgram(paths, OPTIONS, hostWith(new Map(paths.map((p, i) => [p, texts[i]!]))));
  return { program, files: paths.map((p) => program.getSourceFile(p)!) };
};
/** Whether `sf` belongs to a library (node_modules, or the TypeScript lib), not to this project. */
const fromLibrary = (program: ts.Program, sf: ts.SourceFile): boolean =>
  program.isSourceFileDefaultLibrary(sf) || program.isSourceFileFromExternalLibrary(sf) || /[\\/]node_modules[\\/]/.test(sf.fileName);
/* The one limit ABOVE the configured detector in this file, and why: the unit of work is one
   whole-program parse and bind of the app's tsconfig.json (every source under src/, with the lib,
   React, Vitest and three.js typings; measured solo ~11-20 s, dominated by parsing). It cannot be
   split into smaller units — every file's types depend on the rest — and it asserts nothing about
   time. It runs in a beforeAll; everything that asserts runs in the tests, each inside the detector. */
const PROGRAM_BUILD_LIMIT = 300_000;
const inTypePosition = (n: ts.Node): boolean => {
  for (let p: ts.Node | undefined = n.parent; p !== undefined && !ts.isStatement(p) && !ts.isSourceFile(p); p = p.parent) if (ts.isTypeNode(p)) return true;
  return false;
};
const brief = (n: ts.Node): string => n.getText(n.getSourceFile()).replace(/\s+/g, " ").slice(0, 60);
/** The identifier a chain of property reads, calls and element reads starts from, looking through parentheses, assertions and `await`. */
const rootIdentifierOf = (e: ts.Expression): ts.Identifier | null => {
  let x: ts.Expression = e;
  for (;;) {
    if (ts.isParenthesizedExpression(x) || ts.isAsExpression(x) || ts.isNonNullExpression(x) || ts.isSatisfiesExpression(x) || ts.isAwaitExpression(x) || ts.isTypeAssertionExpression(x)) x = x.expression;
    else if (ts.isPropertyAccessExpression(x) || ts.isElementAccessExpression(x) || ts.isCallExpression(x)) x = x.expression;
    else if (ts.isTaggedTemplateExpression(x)) x = x.tag;
    else return ts.isIdentifier(x) ? x : null;
  }
};
const rootNameOf = (e: ts.Expression): string | null => rootIdentifierOf(e)?.text ?? null;
/** The local names a declaration's name binds (an identifier, or every name in a binding pattern). */
const bindingNames = (name: ts.BindingName): string[] =>
  ts.isIdentifier(name) ? [name.text] : name.elements.flatMap((el) => (ts.isOmittedExpression(el) ? [] : bindingNames(el.name)));
/** Where Vitest's typings live: the vitest package and the @vitest/* packages it re-exports from. */
const VITEST_TYPINGS = /[\\/]node_modules[\\/](?:vitest|@vitest[\\/][^\\/]+)[\\/]/;

/* ── every act() scope that can be asynchronous goes through the shared helper (acceptance F2) ────
 * An async act() scope that outlives its test corrupts React's process-global act depth, and every
 * later render in the file is queued and never committed (src/test-support/act-turns.ts has the
 * mechanism). The helper stops an abandoned test at its next scope and settles every scope after
 * each test; a raw act() gets neither.
 *
 * WHICH act() CAN BE ASYNCHRONOUS. React's act() takes its asynchronous path exactly when its
 * callback returns a thenable (react.development.js `exports.act`: `"object" === typeof result &&
 * "function" === typeof result.then`); only then does the scope stay open, holding the act depth,
 * until someone calls `.then` on what act() returned. A callback that returns anything else closes
 * the scope before act() returns, whatever the caller then does with the result: awaiting that
 * result only schedules one self-completing flush task and never touches the depth. So the rule is
 * about the CALLBACK, decided by proof, not by syntax the caller happens to use:
 *
 *   a use of React's act is allowed raw only when it is a direct call with ONE inline, non-async,
 *   non-generator function every value of which is PROVED not to be a thenable.
 *
 * WHAT COUNTS AS PROOF, value by value (a block body's own `return`s; no `return` proves undefined):
 *   - a value whose syntax makes it primitive: a literal or template, `void x`, a unary, arithmetic,
 *     comparison or assignment-by-operator expression (and `a && b`, `a ? b : c`, `a = b` when every
 *     value it can be is proved);
 *   - a value the checker types as primitive and NOT `void` (boolean, number, string, null,
 *     undefined, …): a thenable can wear such a type only through `any` or a type assertion, and an
 *     assertion around the returned value is looked through, not believed;
 *   - a `void` from a call to a function whose body is proved the same way — a function declaration,
 *     or a `const` bound to an arrow or function expression, reached by name (so the value called IS
 *     that function: neither can be reassigned);
 *   - a `void` from a function or method a LIBRARY declares (node_modules, or the TypeScript lib) with
 *     `void` WRITTEN as its return type: `root.render(ui)`, `el.focus()`. That is the library's
 *     contract; see the look-alike rule below. A library return type that is a type parameter, or is
 *     derived from one (`fn.call(…)`, `fn.apply(…)`, `Reflect.apply`, `Object.freeze(x)`), is the
 *     callee's own return passed through, and is proof of nothing (verifier finding R7-V5).
 *
 * NOT PROOF (verifier finding R7-V1): a `void` from any other call. TypeScript lets a function that
 * returns a Promise stand wherever `() => void` is expected — a parameter, a `const pick: () => void
 * = async …`, an `Array<() => void>`, an override of a `run(): void`, an object's method (which can
 * be reassigned) — so a `void` type proves nothing about what such a call returns. The fix at a
 * flagged site is to write the callback as a block, `act(() => { f(); })`, which provably returns
 * undefined. Also reported: an async callback; a callback returning a Promise, an object, `any` or
 * `unknown`; a callback passed by name; act() called with another arity; and React's act used as a
 * VALUE at all — stored (`const a = act`), re-exported, put in an object, `act.call(…)`. Verifier
 * finding F2-R2-1: an earlier scan flagged only calls that were awaited, chained or handed an inline
 * async function, so a returned, stored, wrapped or aliased raw scope passed.
 *
 * LOOK-ALIKES. Trusting a library's `void` assumes the object called is the library's. A function
 * that returns a thenable, written where the checker types it as a library member declared `void`
 * — an object literal's member (`const root: Root = { render: async () => {} }`), a class method
 * implementing one, an assignment over one (`el.focus = async () => {}`), or a Vitest mock's
 * implementation (`vi.spyOn(el, "focus").mockImplementation(async () => {})`) — is reported where it
 * is written, as is a mock of such a member made to return a thenable by value (`mockResolvedValue`,
 * `mockReturnValue(promise)`). The scan judges EVERY checked source under src/, whatever words it contains
 * (verifier finding R7-V2-2: a helper that never named act or react was never read).
 *
 * MOCKS VOID PROOFS (verifier finding R7-V2-2). A proof trusts that the value called IS the declared function
 * (or the library's member); a Vitest mock replaces it at run time. So every declaration that a `vi.spyOn(obj,
 * name)` or a `vi.mock`/`vi.doMock` WITH a factory anywhere in the program can replace (`mockCensus`) proves
 * nothing, and a file that registers a mock whose module the scan cannot resolve proves nothing at all. An
 * automock (no factory) makes each export a `vi.fn()` returning undefined, and voids no proof.
 *
 * WHAT COUNTS AS REACT'S act, decided by the checker: any name whose SYMBOL resolves to it, through every
 * alias (an import alias, an import-equals `import a = React.act` — verifier finding R7-V2-1 — which is also
 * reported as act stored under another name), a destructured alias of it, a `.act` property, or an `["act"]` key that resolves to the `act` export
 * of the module "react" resolves to, or whose type IS that export's type. One whose symbol or type
 * cannot be resolved (`require("react")` is `any`) counts as React's: failing closed. Reaching act
 * WITHOUT naming it is reported where the value that carries it escapes typing (verifier finding
 * R7-V3): a computed key, or a computed destructuring key, on any value whose type carries React's
 * act; a `for…in` over one; and one passed where the parameter no longer types its act as React's
 * (`Object.values(React)`). One passed where it stays typed is followed: when what comes back IS
 * React's act (`Reflect.get(React, "act")`, a generic pick), that call is judged as a use of act.
 * Such a value is also FOLLOWED from where it is bound (an import of React, a local bound from one,
 * `await import("react")`) through whatever passes it on unchanged, and reported where it lands out
 * of the scan's sight: a slot whose type no longer carries act (`const R: any = React`, `React as
 * any`, a choice with a value that lacks it), an assignment, a function's result, or an export
 * (including `export * from "react"`) — the last because a file that never names act or react is
 * never read, and could reach act through it by a computed key. The one place it may be returned is
 * a `vi.mock`/`vi.doMock` factory of React, which hands it back to React's own name; a member named
 * act (or computed) written in such a factory is reported as act replaced. Such a factory is found by what
 * the call NAMES (verifier finding R7-V2-3): a specifier string, a const typed as one, or Vitest's
 * `import("react")` form, and a factory inline or passed by name; one the scan cannot read is reported. A
 * LITERAL holding React's module handed to a call is judged by the parameter the callee DECLARES
 * (`Object.assign(globalThis, { R: React })`, `Object.defineProperty(o, "R", { value: React })`), and a
 * specifier written in any quote (``require(`react`)``) counts as React's.
 *
 * WHAT IT DOES NOT SEE, stated rather than implied: a thenable that wears a non-void primitive type
 * through `any` or an assertion written somewhere other than the returned value; a library's
 * implementation replaced where no type describes it, other than by a member named act in a React
 * `vi.mock` factory (`Object.assign` or `Object.defineProperty` onto a library object, prototype
 * patching, a factory of a module that re-exports React); a computed key on a value that is `any`
 * at its root (`(globalThis as any).x[k]`) which no React binding flowed into in a file read here.
 * The runtime canary in src/test-support/test-setup.ts is the backstop for those.
 *
 * WHY A CHECKER AND NOT TEXT. A text stripper cannot tell a regex literal from division (a quote in
 * `/'s IP address$/` hid a raw scope in CommandPalette.test.tsx: F2-V1), and syntax alone cannot
 * tell `act(() => root.render(ui))` (void, React's) from `act(() => sleep(10))` (a Promise). */
describe("every act() scope in src/ that can be asynchronous goes through src/test-support/act-turns.ts", () => {
  const HELPER = "src/test-support/act-turns.ts";
  const REACT_MODULE = /^(?:react(?:-dom)?(?:\/.*)?|@testing-library\/react)$/;
  const unparen = (e: ts.Expression): ts.Expression => (ts.isParenthesizedExpression(e) ? unparen(e.expression) : e);
  /* A file can reach act only by naming it or by holding a value whose TYPE carries it (a React import
     is written `react`); the files that contain neither word cannot hold a use, so they are not read. */
  const NAMES_ACT = /\bact\b|["']react(?:-dom)?(?:\/[^"']*)?["']/;

  interface Scan {
    program: ts.Program;
    checker: ts.TypeChecker;
    /** React's `act` export, and its type (what an alias of it has). */
    act: ts.Symbol;
    actType: ts.Type;
    /** Every declaration a Vitest mock anywhere in the program can replace, with where (R7-V2-2). */
    mocked: Map<ts.Node, string>;
    /** The files that mock a module the scan cannot resolve, with where: any proof in them may be replaced. */
    opaqueMocks: Map<ts.SourceFile, string>;
  }
  /** The one string an expression can be, by its type (a literal, a const bound to one); null when not one knowable string. */
  const literalText = (checker: ts.TypeChecker, e: ts.Expression): string | null => {
    const x = e;
    if (ts.isStringLiteralLike(x)) return x.text;
    const t = checker.getTypeAtLocation(x);
    return t.isStringLiteral() ? t.value : null;
  };
  /** Whether a call's callee is Vitest's own function of one of these names (resolved to Vitest's typings). */
  const vitestCall = (checker: ts.TypeChecker, call: ts.CallExpression, names: RegExp): boolean => {
    let c: ts.Expression = call.expression;
    while (ts.isParenthesizedExpression(c) || ts.isNonNullExpression(c)) c = c.expression;
    const nm = ts.isPropertyAccessExpression(c) ? c.name : ts.isIdentifier(c) ? c : undefined;
    if (nm === undefined || !names.test(nm.text)) return false;
    let s = checker.getSymbolAtLocation(nm);
    if (s !== undefined && s.flags & ts.SymbolFlags.Alias) s = checker.getAliasedSymbol(s);
    return s?.declarations?.some((d) => VITEST_TYPINGS.test(d.getSourceFile().fileName)) === true;
  };
  /** The module specifier a vi.mock/vi.doMock names: a string (or a const typed as one), or Vitest's `import("…")` form. */
  const mockSpecifier = (checker: ts.TypeChecker, e: ts.Expression | undefined): string | null => {
    if (e === undefined) return null;
    let x = e;
    while (ts.isParenthesizedExpression(x) || ts.isAwaitExpression(x)) x = x.expression;
    if (ts.isCallExpression(x) && x.expression.kind === ts.SyntaxKind.ImportKeyword) {
      const a = x.arguments[0];
      return a === undefined ? null : literalText(checker, a);
    }
    return literalText(checker, x);
  };
  /**
   * WHAT A VITEST MOCK CAN REPLACE, over EVERY project source of the program — tests and the helpers they call
   * alike, whatever words they contain (independent verifier R7-V2-2: a spy installed in a helper that never
   * names act or react was never read). `vi.spyOn(obj, name)` replaces that member of obj's type (every member,
   * when the name cannot be read); `vi.mock`/`vi.doMock` with a factory replaces every export of the module it
   * names (an automock without one makes each export a `vi.fn()` that returns undefined, and replaces no proof);
   * a specifier the scan cannot resolve replaces anything, in the file that registers it. A void-call proof is
   * void for a declaration in this census: at run time the value called need not be that function at all.
   */
  const mockCensus = (program: ts.Program, checker: ts.TypeChecker): { mocked: Map<ts.Node, string>; opaqueMocks: Map<ts.SourceFile, string> } => {
    const mocked = new Map<ts.Node, string>();
    const opaqueMocks = new Map<ts.SourceFile, string>();
    const add = (s0: ts.Symbol | undefined, where: string): void => {
      const s = s0 !== undefined && s0.flags & ts.SymbolFlags.Alias ? checker.getAliasedSymbol(s0) : s0;
      for (const d of s?.declarations ?? []) {
        if (!mocked.has(d)) mocked.set(d, where);
        if (ts.isVariableDeclaration(d) && d.initializer !== undefined) {
          let init: ts.Expression = d.initializer;
          while (ts.isParenthesizedExpression(init) || ts.isAsExpression(init) || ts.isSatisfiesExpression(init)) init = init.expression;
          if (!mocked.has(init)) mocked.set(init, where);
        }
      }
    };
    const resolutionHost: ts.ModuleResolutionHost = {
      fileExists: (f) => program.getSourceFile(f) !== undefined || ts.sys.fileExists(f),
      readFile: (f) => program.getSourceFile(f)?.text ?? ts.sys.readFile(f),
      directoryExists: (d) => ts.sys.directoryExists(d) || program.getSourceFiles().some((sf) => resolve(sf.fileName).startsWith(`${resolve(d)}${sep}`)),
    };
    for (const sf of program.getSourceFiles()) {
      if (fromLibrary(program, sf)) continue;
      const where = (n: ts.Node): string => `${rel(sf.fileName)}:${sf.getLineAndCharacterOfPosition(n.getStart(sf)).line + 1}`;
      const visit = (n: ts.Node): void => {
        if (ts.isCallExpression(n)) {
          if (n.arguments.length >= 2 && vitestCall(checker, n, /^spyOn$/)) {
            const objType = checker.getApparentType(checker.getNonNullableType(checker.getTypeAtLocation(n.arguments[0]!)));
            const name = literalText(checker, n.arguments[1]!);
            for (const p of name === null ? checker.getPropertiesOfType(objType) : [checker.getPropertyOfType(objType, name)]) add(p, where(n));
          } else if (n.arguments.length >= 2 && vitestCall(checker, n, /^(?:mock|doMock)$/)) {
            const spec = mockSpecifier(checker, n.arguments[0]);
            const file = spec === null ? undefined : ts.resolveModuleName(spec, sf.fileName, OPTIONS, resolutionHost).resolvedModule?.resolvedFileName;
            const target = file === undefined ? undefined : program.getSourceFile(file);
            if (spec === null || file === undefined) {
              if (!opaqueMocks.has(sf)) opaqueMocks.set(sf, where(n));
            } else if (target !== undefined) {
              const moduleSymbol = checker.getSymbolAtLocation(target);
              if (moduleSymbol !== undefined) for (const e of checker.getExportsOfModule(moduleSymbol)) add(e, where(n));
            }
          }
        }
        ts.forEachChild(n, visit);
      };
      visit(sf);
    }
    return { mocked, opaqueMocks };
  };
  const scanOf = (program: ts.Program): Scan => {
    const checker = program.getTypeChecker();
    /* React's act is whatever the module "react" resolves to from src/ exports as `act` — found through
       module resolution, not a path written here. Failing closed: no act found, no scan. */
    const typings = ts.resolveModuleName("react", resolve(SRC, "main.tsx"), OPTIONS, ts.sys).resolvedModule?.resolvedFileName;
    const moduleFile = typings === undefined ? undefined : program.getSourceFile(typings);
    const moduleSymbol = moduleFile === undefined ? undefined : checker.getSymbolAtLocation(moduleFile);
    const exported = moduleSymbol === undefined ? undefined : checker.getExportsOfModule(moduleSymbol).find((s) => s.name === "act");
    if (exported === undefined) throw new Error(`React's act could not be found through "react" (typings: ${typings ?? "unresolved"})`);
    const act = exported.flags & ts.SymbolFlags.Alias ? checker.getAliasedSymbol(exported) : exported;
    return { program, checker, act, actType: checker.getTypeOfSymbol(act), ...mockCensus(program, checker) };
  };

  const PRIMITIVE =
    ts.TypeFlags.Void |
    ts.TypeFlags.Undefined |
    ts.TypeFlags.Null |
    ts.TypeFlags.BooleanLike |
    ts.TypeFlags.NumberLike |
    ts.TypeFlags.StringLike |
    ts.TypeFlags.BigIntLike |
    ts.TypeFlags.ESSymbolLike |
    ts.TypeFlags.Never;
  const primitiveOnly = (t: ts.Type): boolean => (t.isUnion() ? t.types.every(primitiveOnly) : (t.flags & PRIMITIVE) !== 0 && (t.flags & (ts.TypeFlags.Any | ts.TypeFlags.Unknown)) === 0);
  const hasVoid = (t: ts.Type): boolean => (t.isUnion() ? t.types.some(hasVoid) : (t.flags & ts.TypeFlags.Void) !== 0);
  /** Whether `n` is the NAME a declaration introduces (not a use of a value). */
  const declaresName = (n: ts.Identifier): boolean => {
    const p = n.parent;
    if (ts.isImportSpecifier(p) || ts.isImportClause(p) || ts.isNamespaceImport(p) || ts.isBindingElement(p)) return true;
    if (ts.isJsxAttribute(p) || ts.isLabeledStatement(p) || ts.isBreakOrContinueStatement(p)) return true;
    const named = p as ts.Node & { name?: ts.Node };
    return named.name === n && !ts.isPropertyAccessExpression(p) && !ts.isShorthandPropertyAssignment(p) && !ts.isExportSpecifier(p);
  };
  /** The value under the syntax that does not change it. A type assertion proves nothing, so the value it wraps is what is judged. */
  const underneath = (e: ts.Expression): ts.Expression =>
    ts.isParenthesizedExpression(e) || ts.isNonNullExpression(e) || ts.isSatisfiesExpression(e) || ts.isAsExpression(e) || ts.isTypeAssertionExpression(e) ? underneath(e.expression) : e;
  /** The values a function body returns: its own `return`s, not a nested function's. */
  const returnsOf = (body: ts.Block): ts.Expression[] => {
    const out: ts.Expression[] = [];
    const visit = (n: ts.Node): void => {
      if (ts.isFunctionLike(n) || ts.isClassLike(n)) return;
      if (ts.isReturnStatement(n) && n.expression !== undefined) out.push(n.expression);
      ts.forEachChild(n, visit);
    };
    ts.forEachChild(body, visit);
    return out;
  };
  /* Any quote a specifier can be written in — a template literal too (R7-V2-3: ``require(`react`)``). */
  const REACT_SPECIFIER = /["'`](?:react(?:-dom)?(?:\/[^"'`]*)?|@testing-library\/react)["'`]/;
  const MOCK_METHOD = /^(?:mock|with)/;
  const vitestDeclared = (t: ts.Type): boolean =>
    (t.isUnion() || t.isIntersection() ? t.types : [t]).some((u) => [u.symbol, u.aliasSymbol].some((s) => s?.declarations?.some((d) => VITEST_TYPINGS.test(d.getSourceFile().fileName)) === true));
  const LOGICAL = new Set([
    ts.SyntaxKind.AmpersandAmpersandToken,
    ts.SyntaxKind.BarBarToken,
    ts.SyntaxKind.QuestionQuestionToken,
    ts.SyntaxKind.AmpersandAmpersandEqualsToken,
    ts.SyntaxKind.BarBarEqualsToken,
    ts.SyntaxKind.QuestionQuestionEqualsToken,
  ]);
  const ALWAYS_PRIMITIVE = new Set([
    ts.SyntaxKind.NumericLiteral,
    ts.SyntaxKind.BigIntLiteral,
    ts.SyntaxKind.StringLiteral,
    ts.SyntaxKind.NoSubstitutionTemplateLiteral,
    ts.SyntaxKind.TemplateExpression,
    ts.SyntaxKind.TrueKeyword,
    ts.SyntaxKind.FalseKeyword,
    ts.SyntaxKind.NullKeyword,
    ts.SyntaxKind.VoidExpression,
    ts.SyntaxKind.TypeOfExpression,
    ts.SyntaxKind.DeleteExpression,
    ts.SyntaxKind.PrefixUnaryExpression,
    ts.SyntaxKind.PostfixUnaryExpression,
  ]);

  /** Each use of React's act in one file that is not a proven-synchronous direct call, and each look-alike or escape, as `line:col why: text`. */
  const offendersIn = (scan: Scan, sf: ts.SourceFile): string[] => {
    const { program, checker, act, actType } = scan;
    const found: string[] = [];
    const report = (at: ts.Node, why: string): void => {
      const { line, character } = sf.getLineAndCharacterOfPosition(at.getStart(sf));
      found.push(`${line + 1}:${character + 1} ${why}: ${brief(at)}`);
    };
    /* Local names bound from something named act: `import { act as x }`, `const { act: x } = …`. */
    const names = new Set(["act"]);
    const reactObjects = new Set<string>();
    const locals: ts.VariableDeclaration[] = [];
    const collect = (n: ts.Node): void => {
      if (ts.isVariableDeclaration(n) && n.initializer !== undefined) locals.push(n);
      if ((ts.isImportSpecifier(n) || ts.isBindingElement(n)) && n.propertyName !== undefined && ts.isIdentifier(n.name)) {
        const from = n.propertyName;
        if ((ts.isIdentifier(from) || ts.isStringLiteral(from)) && from.text === "act") names.add(n.name.text);
      }
      if (ts.isImportDeclaration(n) && ts.isStringLiteral(n.moduleSpecifier) && REACT_MODULE.test(n.moduleSpecifier.text) && n.importClause !== undefined) {
        if (n.importClause.name !== undefined) reactObjects.add(n.importClause.name.text);
        const b = n.importClause.namedBindings;
        if (b !== undefined && ts.isNamespaceImport(b)) reactObjects.add(b.name.text);
      }
      ts.forEachChild(n, collect);
    };
    collect(sf);
    /* The names that may hold React's module object, and so act, without naming act: its default and
       namespace imports, and every local bound from one or from an import of React (`await import("react")`,
       `importOriginal<typeof import("react")>()`), to a fixpoint. Found by syntax, so that only these (and
       parameters, whose values come from elsewhere) are handed to the checker; the checker then decides. */
    const carriers = new Set(reactObjects);
    /** Whether `e` may evaluate to a carrier itself (not to something read from one): a carrier name, an import of
        React, a call handed a carrier or typed with React's module (a generic pick, `importOriginal<typeof
        import("react")>()`), a literal holding one, or a choice between such values. */
    const carrierExpression = (e: ts.Expression): boolean => {
      const x = underneath(ts.isAwaitExpression(e) ? e.expression : e);
      if (ts.isAwaitExpression(x)) return carrierExpression(x.expression);
      if (ts.isIdentifier(x)) return carriers.has(x.text);
      if (ts.isCallExpression(x)) return REACT_SPECIFIER.test(x.getText(sf)) || x.arguments.some((arg) => carrierExpression(ts.isSpreadElement(arg) ? arg.expression : arg));
      if (ts.isArrayLiteralExpression(x)) return x.elements.some((el) => carrierExpression(ts.isSpreadElement(el) ? el.expression : el));
      if (ts.isObjectLiteralExpression(x)) {
        return x.properties.some((p) =>
          ts.isSpreadAssignment(p) ? carrierExpression(p.expression) : ts.isPropertyAssignment(p) ? carrierExpression(p.initializer) : ts.isShorthandPropertyAssignment(p) && carriers.has(p.name.text),
        );
      }
      if (ts.isConditionalExpression(x)) return carrierExpression(x.whenTrue) || carrierExpression(x.whenFalse);
      if (ts.isBinaryExpression(x)) return carrierExpression(x.left) || carrierExpression(x.right);
      return false;
    };
    for (let grew = true; grew; ) {
      grew = false;
      for (const d of locals) {
        if (!carrierExpression(d.initializer!)) continue;
        for (const bound of bindingNames(d.name)) {
          if (carriers.has(bound)) continue;
          carriers.add(bound);
          grew = true;
        }
      }
    }

    /** React's act, or unresolvable (counted as React's), for the value at `ref`; false for any other act. */
    const isReactAct = (ref: ts.Expression, symbol: ts.Symbol | undefined): boolean => {
      let s = symbol;
      if (s !== undefined && s.flags & ts.SymbolFlags.Alias) s = checker.getAliasedSymbol(s);
      if (s === act) return true;
      const type = checker.getTypeAtLocation(ref);
      if (type === actType) return true;
      return s === undefined || (type.flags & (ts.TypeFlags.Any | ts.TypeFlags.Unknown)) !== 0;
    };
    /** Whether a value of type `t` carries React's act as a property, so a key it is read by decides whether act is reached. */
    const carriesAct = (t: ts.Type): boolean => {
      if (t.flags & (ts.TypeFlags.Any | ts.TypeFlags.Unknown)) return false;
      const p = checker.getPropertyOfType(checker.getApparentType(checker.getNonNullableType(t)), "act");
      if (p === undefined) return false;
      const target = p.flags & ts.SymbolFlags.Alias ? checker.getAliasedSymbol(p) : p;
      return target === act || checker.getTypeOfSymbol(target) === actType;
    };
    /** Whether `e` is a value that carries React's act: decided by the checker for the candidates above and for parameters. */
    const isReactObject = (e: ts.Expression): boolean => {
      const x = unparen(e);
      if (ts.isIdentifier(x) && reactObjects.has(x.text)) return true;
      const type = checker.getTypeAtLocation(underneath(x));
      /* An import of React the checker cannot type (`require("react")` is `any`) counts as React's: failing closed. */
      if (carrierExpression(x) && (type.flags & (ts.TypeFlags.Any | ts.TypeFlags.Unknown)) !== 0) return true;
      const root = rootIdentifierOf(x);
      if (root === null) return false;
      const candidate = carriers.has(root.text) || (checker.getSymbolAtLocation(root)?.valueDeclaration?.kind === ts.SyntaxKind.Parameter);
      /* The value's own type, under any assertion: `(R as Record<string, unknown>)[k]` still reads React's module. */
      return candidate && carriesAct(type);
    };
    /** Whether a value of type `t` carries React's act, or holds one that does one level down (an element, a property). */
    const holdsAct = (t: ts.Type): boolean => {
      if (carriesAct(t)) return true;
      const x = checker.getApparentType(checker.getNonNullableType(t));
      if (checker.isArrayType(x) || checker.isTupleType(x)) return checker.getTypeArguments(x as ts.TypeReference).some(carriesAct);
      return (x.flags & ts.TypeFlags.Object) !== 0 && checker.getPropertiesOfType(x).some((p) => carriesAct(checker.getTypeOfSymbol(p)));
    };
    /** holdsAct, `depth` levels down (an array of tuples of React's module, a property of a property). */
    const holdsActDeep = (t: ts.Type, depth: number): boolean => {
      if (carriesAct(t)) return true;
      if (depth <= 0 || (t.flags & (ts.TypeFlags.Any | ts.TypeFlags.Unknown | ts.TypeFlags.TypeParameter)) !== 0) return false;
      const x = checker.getApparentType(checker.getNonNullableType(t));
      if (checker.isArrayType(x) || checker.isTupleType(x)) return checker.getTypeArguments(x as ts.TypeReference).some((u) => holdsActDeep(u, depth - 1));
      return (x.flags & ts.TypeFlags.Object) !== 0 && checker.getPropertiesOfType(x).some((p) => holdsActDeep(checker.getTypeOfSymbol(p), depth - 1));
    };
    /**
     * Follow a value that carries React's act up through the expressions that pass it on, and report where it
     * lands somewhere the scan does not follow it: a slot whose type no longer carries act (`const R: any =
     * React`, `React as any`, a choice with a value that lacks it), a store the scan does not track (an
     * assignment, a property of something else), a function's result, or an export — from where a file that
     * never names act or react, and so is never read, can reach act by a computed key. The planted cases pin each.
     * A member read, a key, a `for…in` and a call argument are where it is judged (above and below); passing it on
     * unchanged (parentheses, `await`, a literal that still types it) is followed.
     */
    const follow = (e: ts.Expression): void => {
      const p = e.parent;
      const escapes = (why: string): void => report(e, `a value that carries React's act ${why}, so whether act is reached through it cannot be resolved`);
      const onward = (next: ts.Expression, why: string): void => (holdsAct(checker.getTypeAtLocation(next)) ? follow(next) : escapes(why));
      if (ts.isPropertyAccessExpression(p) || ts.isElementAccessExpression(p)) return p.expression === e ? undefined : escapes("used as a key");
      if (ts.isCallExpression(p) || ts.isNewExpression(p) || ts.isForInStatement(p) || ts.isTypeOfExpression(p) || ts.isVoidExpression(p)) return;
      if (ts.isSpreadElement(p) && (ts.isCallExpression(p.parent) || ts.isNewExpression(p.parent))) return;
      if (ts.isParenthesizedExpression(p) || ts.isNonNullExpression(p) || ts.isAwaitExpression(p)) return onward(p, "passed on");
      if (ts.isAsExpression(p) || ts.isTypeAssertionExpression(p) || ts.isSatisfiesExpression(p)) return onward(p, "asserted to a type that no longer carries it");
      if (ts.isConditionalExpression(p)) return p.condition === e ? undefined : onward(p, "chosen with a value that does not carry it");
      if (ts.isBinaryExpression(p)) {
        const op = p.operatorToken.kind;
        if (op === ts.SyntaxKind.CommaToken) return p.right === e ? onward(p, "passed on") : undefined;
        if (LOGICAL.has(op) && op !== ts.SyntaxKind.AmpersandAmpersandEqualsToken && op !== ts.SyntaxKind.BarBarEqualsToken && op !== ts.SyntaxKind.QuestionQuestionEqualsToken) {
          return onward(p, "combined with a value that does not carry it");
        }
        if (op === ts.SyntaxKind.EqualsToken && p.right === e) return escapes("assigned where the scan does not follow it");
        return p.right === e || p.left === e ? escapes("used in an expression the scan does not follow") : undefined;
      }
      if (ts.isArrayLiteralExpression(p)) return onward(p, "put in an array typed without it");
      if (ts.isSpreadElement(p) && ts.isArrayLiteralExpression(p.parent)) return onward(p.parent, "spread into an array typed without it");
      if ((ts.isPropertyAssignment(p) && p.initializer === e) || ts.isShorthandPropertyAssignment(p) || ts.isSpreadAssignment(p)) {
        return onward(p.parent as ts.ObjectLiteralExpression, "put in an object typed without it");
      }
      if (ts.isVariableDeclaration(p) && p.initializer === e) {
        if ((ts.getCombinedModifierFlags(p) & ts.ModifierFlags.Export) !== 0) return escapes("exported");
        return holdsAct(checker.getTypeAtLocation(p.name)) ? undefined : escapes("stored where its type no longer carries it");
      }
      if (ts.isExportSpecifier(p) || ts.isExportAssignment(p)) return escapes("exported");
      /* Returned from a vi.mock factory of React: handed back to React's own name, where every use is judged as React's. */
      if (ts.isReturnStatement(p) || (ts.isArrowFunction(p) && p.body === e)) {
        const fn = ts.isArrowFunction(p) ? p : ts.findAncestor(p, ts.isFunctionLike);
        if (fn !== undefined && reactMockFactory(fn)) return;
      }
      escapes(`passed on (${ts.SyntaxKind[p.kind]})`);
    };
    /* The factories handed to Vitest's `vi.mock`/`vi.doMock` for a React module, found by what the call NAMES
       (R7-V2-3): a specifier that is a string, a const typed as one, or Vitest's `import("react")` form; and a
       factory written inline OR passed by name (resolved to the function it is bound to). A factory the scan
       cannot read — a call's result, a function from another module — is reported where it is handed over. A
       mock whose specifier cannot be read at all may be React's: its inline factory is read for an act member,
       but it gets no allowance to hand React back. */
    const reactFactories = new Set<ts.Node>();
    const maybeReactFactories = new Set<ts.Node>();
    const collectFactories = (n: ts.Node): void => {
      if (ts.isCallExpression(n) && n.arguments.length >= 2 && vitestCall(checker, n, /^(?:mock|doMock)$/)) {
        const spec = mockSpecifier(checker, n.arguments[0]);
        const react = spec !== null && REACT_MODULE.test(spec);
        if (spec === null || react) {
          const into = react ? reactFactories : maybeReactFactories;
          const f = unparen(n.arguments[1]!);
          let fn: ts.Node | undefined;
          if (ts.isArrowFunction(f) || ts.isFunctionExpression(f)) fn = f;
          else if (ts.isIdentifier(f)) {
            let s = checker.getSymbolAtLocation(f);
            if (s !== undefined && s.flags & ts.SymbolFlags.Alias) s = checker.getAliasedSymbol(s);
            const d = s?.valueDeclaration;
            if (d !== undefined && ts.isFunctionDeclaration(d)) fn = d;
            else if (d !== undefined && ts.isVariableDeclaration(d) && d.initializer !== undefined) {
              const init = unparen(d.initializer);
              if (ts.isArrowFunction(init) || ts.isFunctionExpression(init)) fn = init;
            }
          }
          if (fn === undefined || fn.getSourceFile() !== sf) {
            if (react) report(n, "a vi.mock factory of React the scan cannot read (not a function written in this file), which may replace act where no type describes it");
          } else into.add(fn);
        }
      }
      ts.forEachChild(n, collectFactories);
    };
    collectFactories(sf);
    /** Whether `fn` is a factory handed to Vitest's `vi.mock`/`vi.doMock` for a React module. */
    const reactMockFactory = (fn: ts.Node): boolean => reactFactories.has(fn);

    /** Why a call's `void` result is not proved to be a non-thenable, or null when it is. */
    const whyVoidCall = (call: ts.CallExpression, seen: Set<ts.Node>): string | null => {
      const signature = checker.getResolvedSignature(call);
      const d = signature?.declaration;
      const typed = signature === undefined ? "?" : checker.signatureToString(signature);
      const unproved = `\`${brief(call)}\` returns \`void\` through a value typed \`${typed}\`, and a void return admits a Promise-returning function (write the callback as a block, { …; }, so it returns undefined)`;
      if (d === undefined || ts.isJSDocSignature(d)) return unproved;
      /* The value called: the symbol its name resolves to, through import aliases. */
      const callee = underneath(call.expression);
      const named = ts.isIdentifier(callee) ? callee : ts.isPropertyAccessExpression(callee) ? callee.name : undefined;
      let symbol = named === undefined ? undefined : checker.getSymbolAtLocation(named);
      if (symbol !== undefined && symbol.flags & ts.SymbolFlags.Alias) symbol = checker.getAliasedSymbol(symbol);
      /* A Vitest mock anywhere in the program can replace what is called (R7-V2-2): then the value called need not
         be the declared function, and neither its body nor a library's contract proves anything about it. */
      const mockedAt = [d, ...(symbol?.declarations ?? [])].map((x) => scan.mocked.get(x)).find((w) => w !== undefined);
      if (mockedAt !== undefined) return `\`${brief(call)}\` calls a function that can be replaced by a Vitest mock (${mockedAt}), so what it returns is not proved (write the callback as a block, { …; }, so it returns undefined)`;
      const opaque = scan.opaqueMocks.get(call.getSourceFile());
      if (opaque !== undefined) return `\`${brief(call)}\` is called in a file that mocks a module the scan cannot resolve (${opaque}), which may replace it (write the callback as a block, { …; })`;
      /* A library's function or member, called AS that member (`root.render(ui)`, an imported function) —
         not a value merely typed like one (`handler(e)` with `handler: MouseEventHandler`). */
      /* And only a `void` the library WRITES as its return type. A return type that is a type parameter, or
         derived from one (`call<T, A, R>(…): R`, `Reflect.apply`, `Object.freeze<T>(o: T): Readonly<T>`), is
         the callee's own return passed through (verifier finding R7-V5), so it proves no more than that. */
      if (fromLibrary(program, d.getSourceFile())) {
        return libraryMember(d) && d.type?.kind === ts.SyntaxKind.VoidKeyword && symbol?.declarations?.includes(d) === true ? null : unproved;
      }
      /* This project's own function: proved from its body, when the value called can only BE that function. */
      const decl = symbol?.valueDeclaration;
      const fixed =
        decl !== undefined &&
        ((ts.isFunctionDeclaration(decl) && decl === d) ||
          (ts.isVariableDeclaration(decl) &&
            (decl.parent.flags & ts.NodeFlags.Const) !== 0 &&
            decl.type === undefined &&
            decl.initializer !== undefined &&
            underneath(decl.initializer) === d));
      if (!fixed) return unproved;
      const why = whyFunction(d, seen);
      return why === null ? null : `\`${brief(call)}\` calls a function that ${why}`;
    };
    /** Why the value of `e` is not proved to be a non-thenable, or null when it is. */
    const whyValue = (e: ts.Expression, seen: Set<ts.Node>): string | null => {
      const x = underneath(e);
      if (ALWAYS_PRIMITIVE.has(x.kind)) return null;
      if (ts.isConditionalExpression(x)) return whyValue(x.whenTrue, seen) ?? whyValue(x.whenFalse, seen);
      if (ts.isBinaryExpression(x)) {
        const op = x.operatorToken.kind;
        if (op === ts.SyntaxKind.CommaToken || op === ts.SyntaxKind.EqualsToken) return whyValue(x.right, seen);
        if (LOGICAL.has(op)) return whyValue(x.left, seen) ?? whyValue(x.right, seen);
        return null; // every other binary operator yields a primitive
      }
      const type = checker.getTypeAtLocation(x);
      if (!primitiveOnly(type)) return `\`${brief(x)}\` is \`${checker.typeToString(type)}\``;
      if (!hasVoid(type)) return null;
      if (ts.isCallExpression(x)) return whyVoidCall(x, seen);
      return `\`${brief(x)}\` is typed \`void\`, and a void return admits a Promise-returning function`;
    };
    /** Why what `fn` returns is not proved to be a non-thenable, or null. A function already being proved adds no value of its own. */
    const whyFunction = (fn: ts.SignatureDeclaration, seen: Set<ts.Node>): string | null => {
      if (seen.has(fn)) return null;
      seen.add(fn);
      if ((ts.getCombinedModifierFlags(fn as ts.Declaration) & ts.ModifierFlags.Async) !== 0) return "is async";
      if ((ts.isFunctionDeclaration(fn) || ts.isFunctionExpression(fn) || ts.isMethodDeclaration(fn)) && fn.asteriskToken !== undefined) return "is a generator";
      const body = (fn as ts.FunctionLikeDeclarationBase).body;
      if (body === undefined) return "has no body the scan can read";
      if (!ts.isBlock(body)) return whyValue(body, seen);
      for (const r of returnsOf(body)) {
        const why = whyValue(r, seen);
        if (why !== null) return why;
      }
      return null;
    };

    /** The use rule for one reference to React's act. */
    const judge = (ref: ts.Expression): void => {
      let callee: ts.Node = ref;
      let up: ts.Node = ref.parent;
      while (ts.isParenthesizedExpression(up) || ts.isNonNullExpression(up)) {
        callee = up;
        up = up.parent;
      }
      if (!ts.isCallExpression(up) || up.expression !== callee) return report(ref, `React's act used as a value (${ts.SyntaxKind[up.kind]}), so its scope cannot be proved synchronous`);
      if (up.arguments.length !== 1) return report(up, `act() called with ${up.arguments.length} arguments`);
      const fn = unparen(up.arguments[0]!);
      if (!ts.isArrowFunction(fn) && !ts.isFunctionExpression(fn)) return report(up, "the callback is not written inline, so what it returns cannot be proved");
      if ((ts.getCombinedModifierFlags(fn) & ts.ModifierFlags.Async) !== 0) return report(up, "an async callback opens an asynchronous scope");
      if (ts.isFunctionExpression(fn) && fn.asteriskToken !== undefined) return report(up, "a generator callback returns an object");
      const why = whyFunction(fn, new Set());
      if (why !== null) report(up, `the callback's return is not proved to be a non-thenable: ${why}`);
    };

    /* ── look-alikes: a thenable-returning function written where a library member declared void is expected ── */
    /** A function a library declares, or a method of a library interface or class (not a method of an anonymous type literal, which is a typing device such as React's `bivarianceHack`). */
    const libraryMember = (d: ts.SignatureDeclaration): boolean =>
      ts.isFunctionDeclaration(d) || ((ts.isMethodSignature(d) || ts.isMethodDeclaration(d)) && (ts.isInterfaceDeclaration(d.parent) || ts.isClassDeclaration(d.parent)));
    const thenable = (t: ts.Type): boolean =>
      (t.isUnion() ? t.types : [t]).some((u) => {
        const then = checker.getPropertyOfType(checker.getApparentType(u), "then");
        return then !== undefined && checker.getTypeOfSymbol(then).getCallSignatures().length > 0;
      });
    const returnsThenable = (f: ts.SignatureDeclaration): boolean => {
      if ((ts.getCombinedModifierFlags(f as ts.Declaration) & ts.ModifierFlags.Async) !== 0) return true;
      const s = checker.getSignatureFromDeclaration(f);
      return s !== undefined && thenable(checker.getReturnTypeOfSignature(s));
    };
    /** Whether a function returns something at all: an async function, an expression body, or a `return <value>`. */
    const mayReturnThenable = (f: ts.FunctionLikeDeclaration): boolean =>
      (ts.getCombinedModifierFlags(f) & ts.ModifierFlags.Async) !== 0 || (f.body !== undefined && (!ts.isBlock(f.body) || returnsOf(f.body).length > 0));
    /* Where a function can be written to stand in for a library object's member: as a member of an object
       literal, as a class member, or as the implementation handed to a Vitest mock (`spy.mockImplementation`).
       Every method of Vitest's MockInstance that takes a function is named mock… or with… — pinned below —
       so the name selects the candidates and the checker confirms the receiver is a Vitest mock. */
    const standsInForAMember = (f: ts.FunctionLikeDeclaration): boolean => {
      const p = f.parent;
      if (ts.isObjectLiteralExpression(p) || ts.isClassLike(p)) return true;
      if (ts.isPropertyAssignment(p) && p.initializer === f) return true;
      /* Assigned over a member: `el.focus = async () => {}`. */
      if (ts.isBinaryExpression(p) && p.operatorToken.kind === ts.SyntaxKind.EqualsToken && p.right === f) return true;
      return ts.isCallExpression(p) && p.arguments.includes(f as ts.Expression) && mockedBy(p) !== undefined;
    };
    /** For a call of a Vitest mock's installer (`spy.mockImplementation(…)`), the type of the function it mocks — the
        mock's own type argument (`vi.spyOn(el, "focus")` mocks `el.focus`); undefined for any other call. */
    const mockedBy = (call: ts.CallExpression): ts.Type | undefined => {
      const callee = unparen(call.expression);
      if (!ts.isPropertyAccessExpression(callee) || !MOCK_METHOD.test(callee.name.text)) return undefined;
      const mock = checker.getTypeAtLocation(callee.expression);
      if (!vitestDeclared(mock)) return undefined;
      /* `Mock<T>` is an alias of an intersection; `MockInstance<T>` is a reference. Either carries T. */
      const inVitest = (s: ts.Symbol | undefined): boolean => s?.declarations?.some((d) => VITEST_TYPINGS.test(d.getSourceFile().fileName)) === true;
      if (inVitest(mock.aliasSymbol) && mock.aliasTypeArguments?.[0] !== undefined) return mock.aliasTypeArguments[0];
      for (const u of mock.isUnion() || mock.isIntersection() ? mock.types : [mock]) {
        if ((u.flags & ts.TypeFlags.Object) !== 0 && ((u as ts.ObjectType).objectFlags & ts.ObjectFlags.Reference) !== 0 && inVitest(u.symbol)) {
          const first = checker.getTypeArguments(u as ts.TypeReference)[0];
          if (first !== undefined) return first;
        }
      }
      return undefined;
    };
    /** The library members declared void that a type's call signatures are (a mocked `el.focus`, a `Root["render"]`). */
    const libraryVoidSignatures = (slot: ts.Type): string[] => {
      const out: string[] = [];
      for (const u of slot.isUnion() ? slot.types : [slot]) {
        for (const s of u.getCallSignatures()) {
          const d = s.declaration;
          if (d === undefined || ts.isJSDocSignature(d) || !fromLibrary(program, d.getSourceFile())) continue;
          if (!libraryMember(d)) continue;
          if (hasVoid(checker.getReturnTypeOfSignature(s))) out.push(checker.signatureToString(s));
        }
      }
      return out;
    };
    /** The library members declared to return void that `f` is typed as, by where it is written. */
    const libraryVoidSlots = (f: ts.FunctionLikeDeclaration): string[] => {
      const slots: ts.Type[] = [];
      const member = (t: ts.Type | undefined, name: ts.PropertyName | undefined): void => {
        if (t === undefined || name === undefined || !(ts.isIdentifier(name) || ts.isStringLiteral(name) || ts.isPrivateIdentifier(name))) return;
        const p = checker.getPropertyOfType(t, name.text);
        if (p !== undefined) slots.push(checker.getTypeOfSymbol(p));
      };
      const mocked = ts.isCallExpression(f.parent) ? mockedBy(f.parent) : undefined;
      if (mocked !== undefined) {
        slots.push(mocked);
      } else if ((ts.isArrowFunction(f) || ts.isFunctionExpression(f)) && ts.isPropertyAssignment(f.parent)) {
        member(checker.getContextualType(f.parent.parent), f.parent.name);
      } else if (ts.isArrowFunction(f) || ts.isFunctionExpression(f)) {
        const c = checker.getContextualType(f);
        if (c !== undefined) slots.push(c);
      } else if (ts.isMethodDeclaration(f) && ts.isObjectLiteralExpression(f.parent)) {
        member(checker.getContextualType(f.parent), f.name);
      } else if (ts.isMethodDeclaration(f) && ts.isClassLike(f.parent)) {
        for (const clause of f.parent.heritageClauses ?? []) for (const t of clause.types) member(checker.getTypeAtLocation(t), f.name);
      }
      return slots.flatMap(libraryVoidSignatures);
    };

    const visit = (n: ts.Node): void => {
      if (ts.isIdentifier(n) && names.has(n.text) && !inTypePosition(n)) {
        const p = n.parent;
        if (ts.isExportSpecifier(p)) {
          const local = p.parent.parent.moduleSpecifier === undefined ? checker.getExportSpecifierLocalTargetSymbol(p) : checker.getSymbolAtLocation(n);
          if ((p.propertyName ?? p.name) === n && isReactAct(n, local)) report(p, "React's act re-exported, so its uses cannot be proved synchronous");
        } else if (ts.isShorthandPropertyAssignment(p)) {
          if (isReactAct(n, checker.getShorthandAssignmentValueSymbol(p))) report(p, "React's act stored in an object, so its uses cannot be proved synchronous");
        } else if (ts.isPropertyAccessExpression(p) && p.name === n) {
          if (isReactAct(p, checker.getSymbolAtLocation(n))) judge(p);
        } else if (!declaresName(n) && !(ts.isPropertyAssignment(p) && p.name === n) && !(ts.isQualifiedName(p) && p.right === n)) {
          if (isReactAct(n, checker.getSymbolAtLocation(n))) judge(n);
        }
      } else if (ts.isIdentifier(n) && !inTypePosition(n) && !declaresName(n) && !ts.isQualifiedName(n.parent) && !(ts.isPropertyAccessExpression(n.parent) && n.parent.name === n) && !(ts.isPropertyAssignment(n.parent) && n.parent.name === n)) {
        /* BY SYMBOL, whatever the name (R7-V2-1): a name bound by any syntax the list above does not know — an
           import-equals alias (`import a2 = React.act`) — that resolves to React's act is a use of it. */
        let s = checker.getSymbolAtLocation(n);
        if (s !== undefined && s.flags & ts.SymbolFlags.Alias) s = checker.getAliasedSymbol(s);
        if (s === act) judge(n);
      }
      /* An import-equals whose reference IS React's act stores it under another name (R7-V2-1). */
      if (ts.isImportEqualsDeclaration(n) && !ts.isExternalModuleReference(n.moduleReference)) {
        const ref = n.moduleReference;
        let s = checker.getSymbolAtLocation(ts.isQualifiedName(ref) ? ref.right : ref);
        if (s !== undefined && s.flags & ts.SymbolFlags.Alias) s = checker.getAliasedSymbol(s);
        if (s === act) report(n, "React's act used as a value (an import-equals alias), so its uses cannot be proved synchronous");
      }
      if (ts.isElementAccessExpression(n)) {
        const key = n.argumentExpression;
        if (ts.isStringLiteralLike(key) && key.text === "act") {
          if (isReactAct(n, checker.getSymbolAtLocation(key))) judge(n);
        } else if (!ts.isStringLiteralLike(key) && !ts.isNumericLiteral(key) && isReactObject(n.expression)) {
          report(n, "a computed key on a value that carries React's act, so whether it reaches act cannot be resolved");
        }
      }
      if (ts.isBindingElement(n) && n.propertyName !== undefined && ts.isComputedPropertyName(n.propertyName) && ts.isObjectBindingPattern(n.parent)) {
        const source = n.parent.parent;
        const from = ts.isVariableDeclaration(source) && source.initializer !== undefined ? source.initializer : undefined;
        if (carriesAct(checker.getTypeAtLocation(n.parent)) || (from !== undefined && isReactObject(from))) {
          report(n, "a computed key destructured from a value that carries React's act, so whether it reaches act cannot be resolved");
        }
      }
      if (ts.isForInStatement(n) && isReactObject(n.expression)) report(n.expression, "a value that carries React's act enumerated, so whether it reaches act cannot be resolved");
      /* Where a value that carries React's act goes: a name bound to one (an import of React, a local bound from one),
         and `await import("react")`, followed to where it lands. */
      if (ts.isIdentifier(n) && (reactObjects.has(n.text) || carriers.has(n.text)) && !inTypePosition(n) && !declaresName(n)) {
        const p = n.parent;
        const isUse =
          !(ts.isPropertyAccessExpression(p) && p.name === n) &&
          !(ts.isPropertyAssignment(p) && p.name === n) &&
          !(ts.isQualifiedName(p)) &&
          !(ts.isExportSpecifier(p) && ((p.propertyName ?? p.name) !== n || p.parent.parent.moduleSpecifier !== undefined));
        if (isUse && carriesAct(checker.getTypeAtLocation(n))) follow(n);
      }
      if (ts.isAwaitExpression(n) && ts.isCallExpression(n.expression) && n.expression.expression.kind === ts.SyntaxKind.ImportKeyword && carriesAct(checker.getTypeAtLocation(n))) {
        follow(n);
      }
      /* A vi.mock factory of React that writes a member named act: React's act replaced where no type describes it. */
      if (ts.isFunctionLike(n) && (reactMockFactory(n) || maybeReactFactories.has(n))) {
        const members = (x: ts.Node): void => {
          if ((ts.isPropertyAssignment(x) || ts.isShorthandPropertyAssignment(x) || ts.isMethodDeclaration(x) || ts.isGetAccessorDeclaration(x)) && ts.isObjectLiteralExpression(x.parent)) {
            const key = x.name;
            if ((ts.isIdentifier(key) || ts.isStringLiteralLike(key)) && key.text === "act") report(x, "React's act replaced in a vi.mock factory of React, where no type describes the replacement");
            else if (ts.isComputedPropertyName(key)) report(x, "a computed member in a vi.mock factory of React, which may replace act where no type describes it");
          }
          ts.forEachChild(x, members);
        };
        members(n);
      }
      /* React's module re-exported whole, or a member of it that carries act: act then reachable under another module's name. */
      if (ts.isExportDeclaration(n) && n.moduleSpecifier !== undefined && ts.isStringLiteral(n.moduleSpecifier) && REACT_MODULE.test(n.moduleSpecifier.text)) {
        const clause = n.exportClause;
        if (clause === undefined || ts.isNamespaceExport(clause)) report(n, "React's module re-exported whole, so a value that carries React's act leaves this file");
        else {
          for (const spec of clause.elements) {
            let s = checker.getSymbolAtLocation(spec.propertyName ?? spec.name);
            if (s !== undefined && s.flags & ts.SymbolFlags.Alias) s = checker.getAliasedSymbol(s);
            if (s !== undefined && s !== act && holdsAct(checker.getTypeOfSymbol(s))) report(spec, "a value that carries React's act re-exported, so it leaves this file");
          }
        }
      }
      if ((ts.isCallExpression(n) || ts.isNewExpression(n)) && n.arguments !== undefined) {
        for (const [ai, a] of n.arguments.entries()) {
          const x = unparen(ts.isSpreadElement(a) ? a.expression : a);
          /* A LITERAL holding React's module (R7-V2-3: `Object.assign(globalThis, { R: React })`,
             `Object.defineProperty(o, "R", { value: React })`): followed into the parameter it is handed to, as the
             callee DECLARES it — a type parameter, or a type that does not carry act where the literal put it, is
             where the module leaves typing. (The instantiated contextual type is the literal's own, and proves nothing.) */
          if ((ts.isObjectLiteralExpression(x) || ts.isArrayLiteralExpression(x)) && carrierExpression(x)) {
            const decl = ts.isCallExpression(n) || ts.isNewExpression(n) ? checker.getResolvedSignature(n)?.declaration : undefined;
            const param = decl === undefined || ts.isJSDocSignature(decl) ? undefined : decl.parameters[Math.min(ai, decl.parameters.length - 1)];
            const declared = param === undefined ? undefined : checker.getTypeAtLocation(param);
            if (declared === undefined || !holdsActDeep(declared, 3)) report(a, `a literal holding a value that carries React's act passed to \`${brief(n.expression)}\`, where its act is no longer typed as React's`);
            continue;
          }
          if (ts.isFunctionLike(x) || ts.isLiteralExpression(x) || ts.isObjectLiteralExpression(x) || ts.isArrayLiteralExpression(x)) continue;
          if (!isReactObject(x)) continue;
          const slot = ts.isSpreadElement(a) ? undefined : checker.getContextualType(a);
          if (slot === undefined || !carriesAct(slot)) {
            report(a, `a value that carries React's act passed to \`${brief(n.expression)}\`, where its act is no longer typed as React's`);
          } else if (ts.isCallExpression(n) && checker.getTypeAtLocation(n) === actType) {
            /* Still typed, and what comes back IS React's act (`Reflect.get(React, "act")`, a generic pick):
               the call is a use of act without its name, judged like any other. */
            judge(n);
          }
        }
      }
      /* A mock made to return a thenable by value: `spy.mockResolvedValue(x)`, `spy.mockReturnValue(promise)`. */
      if (ts.isCallExpression(n) && n.arguments.length > 0 && n.arguments.every((arg) => !ts.isFunctionLike(unparen(arg)))) {
        const mocked = mockedBy(n);
        const installer = unparen(n.expression);
        if (mocked !== undefined && ts.isPropertyAccessExpression(installer)) {
          const thenableValue = /Resolved|Rejected/.test(installer.name.text) || n.arguments.some((arg) => thenable(checker.getTypeAtLocation(underneath(arg))));
          if (thenableValue) {
            for (const slot of libraryVoidSignatures(mocked)) {
              report(n, `a mock made to return a thenable stands in for \`${slot}\`, which a library declares to return void (a look-alike: a raw act() that calls it would open an asynchronous scope)`);
            }
          }
        }
      }
      if ((ts.isArrowFunction(n) || ts.isFunctionExpression(n) || ts.isMethodDeclaration(n)) && standsInForAMember(n) && mayReturnThenable(n) && returnsThenable(n)) {
        for (const slot of libraryVoidSlots(n)) {
          report(n, `a function that returns a thenable stands in for \`${slot}\`, which a library declares to return void (a look-alike: a raw act() that calls it would open an asynchronous scope)`);
        }
      }
      ts.forEachChild(n, visit);
    };
    visit(sf);
    return found;
  };

  let scan: Scan | undefined;
  const scanned = (): Scan => {
    if (scan === undefined) throw new Error("the program was not built (beforeAll failed)");
    return scan;
  };
  const suspects = codeFiles.filter((f) => f !== HELPER && NAMES_ACT.test(readFileSync(resolve(ROOT, f), "utf8")));
  beforeAll(() => {
    scan = scanOf(treeProgram());
  }, PROGRAM_BUILD_LIMIT);

  it("walked the source tree and found the helper in it", () => {
    expect(codeFiles.length).toBeGreaterThan(50);
    expect(codeFiles).toContain(HELPER);
    expect(suspects.length, "no source names act or React: the scan is reading nothing").toBeGreaterThan(20);
  });

  it("every source that names act is one the checker reads", () => {
    /* A .js/.mjs/.jsx file under src/ is outside tsconfig.json (allowJs is off), so it could not be judged. */
    expect(suspects.filter((f) => !CHECKED.test(f))).toEqual([]);
    const s = scanned();
    const read = new Set(s.program.getSourceFiles().map((sf) => rel(sf.fileName)));
    expect(suspects.filter((f) => !read.has(f))).toEqual([]);
  });

  /* One case per file: the unit of work is split one record per test (vitest.config.ts), so no case
     carries the whole tree's checking, and each finding names its file. EVERY checked source is judged, not only
     the ones that name act or react (independent verifier R7-V2-2): a look-alike — a thenable-returning stand-in
     for a library member declared void — written in a helper that never says either word was never read. */
  const judged = codeFiles.filter((f) => f !== HELPER && CHECKED.test(f));
  describe("no file outside the helper uses React's act in a way that can be asynchronous", () => {
    it.each(judged)("%s", (f) => {
      const s = scanned();
      const found = offendersIn(s, s.program.getSourceFile(resolve(ROOT, f))!);
      expect(found, `act() uses not proved synchronous in ${f}; use actAsync/flushTurns from ${HELPER}, or write the callback inline as a block that returns nothing:\n${found.join("\n")}`).toEqual([]);
    });
  });

  it("the scan resolves React's act at real call sites (the class is not empty)", () => {
    /* The allowed uses are counted, so a resolver that stopped recognising React's act (and so reported
       nothing) cannot read as a clean tree. */
    const s = scanned();
    let calls = 0;
    for (const f of suspects) {
      const sf = s.program.getSourceFile(resolve(ROOT, f))!;
      const visit = (n: ts.Node): void => {
        if (ts.isCallExpression(n)) {
          const e = unparen(n.expression);
          const name = ts.isPropertyAccessExpression(e) ? e.name : ts.isIdentifier(e) ? e : undefined;
          /* Counted where the callee is written `act` (the resolver must still recognise React's): no other call is typed for this count. */
          const sym = name === undefined || name.text !== "act" ? undefined : s.checker.getSymbolAtLocation(name);
          const target = sym !== undefined && sym.flags & ts.SymbolFlags.Alias ? s.checker.getAliasedSymbol(sym) : sym;
          if (target === s.act) calls += 1;
        }
        ts.forEachChild(n, visit);
      };
      visit(sf);
    }
    expect(calls, "React's act was resolved at no call site").toBeGreaterThan(100);
  });

  it("every Vitest mock method that installs a behaviour is one the look-alike scan reads", () => {
    /* The look-alike scan selects a mock's installer by the method's name (mock… or with…) and then
       confirms the receiver is a Vitest mock. The names are Vitest's, read here from its typings: every
       MockInstance method that takes an argument (an implementation, a return value) must match, or the
       scan would not see it. A concrete mock (MockInstance instantiated), so parameters are real types. */
    const { program, files } = plantedProgram("mock-pin", ['import { vi } from "vitest";\nexport const spy = vi.spyOn(document.body, "focus");\n']);
    const checker = program.getTypeChecker();
    const spy = files[0]!.statements.flatMap((st) => (ts.isVariableStatement(st) ? [...st.declarationList.declarations] : []))[0]!;
    const mock = checker.getTypeAtLocation(spy.name);
    expect(vitestDeclared(mock), "vi.spyOn no longer returns a type Vitest declares").toBe(true);
    const installers = checker
      .getPropertiesOfType(mock)
      .filter((p) =>
        checker
          .getTypeOfSymbol(p)
          .getCallSignatures()
          .some((sig) => sig.getParameters().length > 0),
      )
      .map((p) => p.name);
    for (const known of ["mockImplementation", "withImplementation", "mockReturnValue", "mockResolvedValue"]) expect(installers).toContain(known);
    expect(installers.filter((n) => !MOCK_METHOD.test(n))).toEqual([]);
  });

  /** Whether a file calls one of the helper's scope-opening exports. */
  const callsHelper = (sf: ts.SourceFile): boolean => {
    let yes = false;
    const visit = (n: ts.Node): void => {
      if (ts.isCallExpression(n) && ts.isIdentifier(n.expression) && /^(?:actAsync|flushTurns)$/.test(n.expression.text)) yes = true;
      if (!yes) ts.forEachChild(n, visit);
    };
    visit(sf);
    return yes;
  };
  /** The module specifiers a file imports from. */
  const importsOf = (sf: ts.SourceFile): string[] =>
    sf.statements.filter(ts.isImportDeclaration).map((st) => (ts.isStringLiteral(st.moduleSpecifier) ? st.moduleSpecifier.text : ""));

  it("the files that drive React asynchronously do use the helper (the class is not empty)", () => {
    /* Read from the program's own parse of each file (every source under src/ is one of its roots), not re-parsed. */
    const s = scanned();
    const parsed = (f: string): ts.SourceFile => s.program.getSourceFile(resolve(ROOT, f))!;
    const users = codeFiles.filter((f) => f !== HELPER && CHECKED.test(f) && callsHelper(parsed(f)));
    expect(users.length, "no test opens an async act() scope through the helper: the scan is reading nothing").toBeGreaterThan(10);
    /* Every such file imports it, whatever the relative prefix. */
    const fromHelper = (spec: string): boolean => /^(?:\.{1,2}\/)+(?:[\w-]+\/)*test-support\/act-turns(?:\.ts)?$/.test(spec);
    expect(users.filter((f) => !importsOf(parsed(f)).some(fromHelper))).toEqual([]);
  });

  /* Planted texts get React's act imported unless they bring their own imports. Each raw shape names the
     reason it must be reported for, so a shape reported for the WRONG reason (an undeclared name read as
     `any`) cannot stand in for the one it is meant to prove. */
  const PREAMBLE = 'import * as React from "react";\nimport { act } from "react";\n';
  const SLEEP = "const sleep = (ms: number): Promise<void> => new Promise<void>((r) => setTimeout(r, ms));\n";
  /* A text brings its own imports when a line STARTS with `import `, or when it calls `require(` anywhere. Two tests,
     not one alternation, so the line anchor visibly applies to `import ` alone. */
  const withPreamble = (t: string): string => `${/^import /m.test(t) || /require\(/.test(t) ? "" : PREAMBLE}${t}\nexport {};\n`;
  const ASYNC = /async callback/;
  const THENABLE = /not proved to be a non-thenable/;
  /* R7-V1: a `void` that is not a proof, reported as such (not as `any`, not as a Promise type). */
  const VOID = /a void return admits a Promise-returning function/;
  const VALUE = /used as a value|re-exported|stored in an object/;
  const BY_NAME = /not written inline/;
  const CARRIER = /carries React's act/;
  const LOOKALIKE = /look-alike/;
  const MOCKED = /replaced in a vi\.mock factory/;

  const RAW: [string, RegExp][] = [
      ["await act(async () => { await flush(); });", ASYNC],
      ["await act(() => store.set(1));", THENABLE],
      ["await React.act(async () => {});", ASYNC],
      ["void act(async () => {});", ASYNC],
      ["const p = act(async () => {});", ASYNC],
      ["const p = act(async function () {});", ASYNC],
      ["act(() => pending).then(done);", THENABLE],
      ["await (act)(() => store.set(1));", THENABLE],
      /* F2-V1: a quote inside a regex literal before the call. The text stripper this replaced read
         it as the start of a string and swallowed the scope. */
      ["const re = /^matched this [\\w -]+'s \\w/;\nawait act(async () => {});", ASYNC],
      ["const re = /'s IP address$/;\nconst flush = (): Promise<void> => act(async () => {});", ASYNC],
      ['import { act as flushReact } from "react";\nawait flushReact(async () => {});', ASYNC],
      ['import * as R from "react";\nawait R.act(async () => {});', ASYNC],
      /* Not installed here, so `TL` is unresolvable: its act counts as React's (failing closed). */
      ['import TL from "@testing-library/react";\nawait TL.act(async () => {});', ASYNC],
      /* F2-R2-1: returned, stored, wrapped, aliased, named — each passed the scan before that. */
      ["const flush = (): Promise<void> => act(() => new Promise<void>((r) => setTimeout(r, 10)));\nawait flush();", THENABLE],
      ["const tick = async (): Promise<void> => {};\nconst flush = () => act(tick);\nawait flush();", BY_NAME],
      [`${SLEEP}function flush() { return act(() => sleep(10)); }\nawait flush();`, THENABLE],
      ["const a = act;\nawait a(async () => {});", VALUE],
      ['const { act: a } = require("react");\nawait a(async () => {});', ASYNC],
      ["await act.call(null, async () => {});", VALUE],
      [`${SLEEP}await Promise.all([act(() => sleep(10))]);`, THENABLE],
      [`${SLEEP}const p = act(() => sleep(10));\nawait p;`, THENABLE],
      /* Not awaited at all: the scope still opens, and holds the depth until someone calls .then. */
      ["act(() => { return new Promise<void>((r) => setTimeout(r, 1)); });", THENABLE],
      ["const run = (fn: () => void) => act(fn);\nrun(() => {});", BY_NAME],
      ['import ReactDefault from "react";\nawait ReactDefault.act(async () => {});', ASYNC],
      ['const R = await import("react");\nawait R.act(async () => {});', ASYNC],
      ['export { act } from "react";', VALUE],
      ["export { act as flushAll };", VALUE],
      ["const o = { act };\nvoid o;", VALUE],
      ["const o = { run: act };\nvoid o;", VALUE],
      ["const { act: a } = React;\nawait a(async () => {});", ASYNC],
      ['await React["act"](async () => {});', ASYNC],
      ['const key = "act" as const;\nawait React[key](async () => {});', CARRIER],
      ["const cb = (): unknown => undefined;\nact(() => cb());", THENABLE],
      /* An `any` return: nothing is proved about what JSON.parse (or anything typed `any`) returns. (The
         earlier `act((): any => 1)` returns the literal 1 whatever its annotation says; it is proved now,
         and sits in the list below.) */
      ['act((): any => JSON.parse("1"));', THENABLE],
      ["act(() => ({ then() {} }));", THENABLE],
      ["act(() => {}, 1);", /called with 2 arguments/],
      /* Untyped names are `any`: nothing is proved about them, so they are reported, not assumed fine. */
      ["act(() => root.render(ui));", THENABLE],
      ["await j.act(page, 0).catch(() => null);", /called with 2 arguments/],
      /* R7-V1: a `void` type is not a proof. Each of these returns a Promise at run time through a value
         TypeScript types `() => void`; each was passed as proved. */
      [`${SLEEP}const run = (fn: () => void) => act(() => fn());\nrun(async () => { await sleep(10); });`, VOID],
      ["function flush(cb: () => void): void { act(() => cb()); }\nflush(async () => {});", VOID],
      [`${SLEEP}const pick: () => void = async () => { await sleep(10); };\nact(() => pick());`, VOID],
      [`${SLEEP}const pick: () => void = async () => { await sleep(10); };\nact(() => { return pick(); });`, VOID],
      [
        "class Base { run(): void {} }\nclass Sub extends Base { override async run(): Promise<void> {} }\nconst s: Base = new Sub();\nact(() => s.run());",
        VOID,
      ],
      ["const fns: Array<() => void> = [async () => {}];\nact(() => fns[0]!());", VOID],
      /* An object's method can be reassigned (`store.set = async () => {}` type-checks), so it is not a proof either. */
      ["const store = { set(_n: number): void {} };\nawait act(() => store.set(1));", VOID],
      ["const store = { set(_n: number): void {} };\nconst rerender = () => act(() => store.set(2));\nrerender();", VOID],
      /* A function whose body returns an unproved void is not proved by being a declaration. */
      ["const pick: () => void = async () => {};\nfunction relay(): void { return pick(); }\nact(() => relay());", VOID],
      ["const pick: () => void = async () => {};\nconst relay = () => pick();\nact(() => relay());", VOID],
      ["async function later(): Promise<void> {}\nfunction relay() { return later(); }\nact(() => relay());", THENABLE],
      /* R7-V5: a library signature whose `void` is a TYPE PARAMETER instantiated from the call
         (`call<T, A, R>(…): R`, `Reflect.apply`, `Object.freeze<T>(o: T): Readonly<T>`) passes an unproved
         callee's return straight through; that `void` is the callee's, not the library's contract. */
      [`${SLEEP}const pick: () => void = async () => { await sleep(10); };\nact(() => pick.call(null));`, VOID],
      [`${SLEEP}const pick: () => void = async () => { await sleep(10); };\nact(() => pick.apply(null, []));`, VOID],
      [`${SLEEP}const pick: () => void = async () => { await sleep(10); };\nact(() => Reflect.apply(pick, undefined, []));`, VOID],
      [`${SLEEP}const pick: () => void = async () => { await sleep(10); };\nact(() => Object.freeze(pick()));`, VOID],
      [`${SLEEP}const pick: () => void = async () => { await sleep(10); };\nact(function () { return pick.call(null); });`, VOID],
      ["const store = { set(_n: number): void {} };\nact(() => store.set.call(store, 1));", VOID],
      ["const store = { set(_n: number): void {} };\nact(() => store.set.bind(store)(1));", VOID],
      /* A value merely TYPED like a library member is not the library's member. */
      [
        'import { act } from "react";\nimport type { MouseEventHandler } from "react";\nconst onClick: MouseEventHandler = async () => {};\nact(() => onClick({} as never));\nexport {};',
        VOID,
      ],
      /* A library interface's own method type, on a value that is not that member: typed alike, proved nothing. */
      ["declare const focusLike: HTMLElement[\"focus\"];\nact(() => focusLike());", VOID],
      ["const { focus } = document.body;\nact(() => focus());", VOID],
      /* An assertion is looked through, not believed. */
      ["act(() => (Promise.resolve() as unknown as void));", THENABLE],
      ["act(() => (Promise.resolve() as unknown as boolean));", THENABLE],
      /* R7-V3: act reached without naming it, through a value whose type carries it. */
      ['const { ["act"]: a } = React;\nawait a(async () => {});', CARRIER],
      ['const k = "act";\nconst { [k]: a } = React;\nawait a(async () => {});', CARRIER],
      /* Reached through a generic lookup that keeps its type: the call's result IS React's act, and is judged. */
      ['await Reflect.get(React, "act")(async () => {});', ASYNC],
      ['const got = Reflect.get(React, "act");\nawait got(async () => {});', VALUE],
      ['const pick = <T, K extends keyof T>(o: T, k: K): T[K] => o[k];\nawait pick(React, "act")(async () => {});', ASYNC],
      ["const all = [React];\nconst k3 = String(1) as keyof typeof React;\nvoid all[0]![k3];", CARRIER],
      ['const R2 = React;\nconst k2 = "a" + "ct";\nawait (R2 as Record<string, unknown>)[k2];', CARRIER],
      ['const R2 = React;\nconst k2 = ["a", "ct"].join("") as keyof typeof React;\nvoid R2[k2];', CARRIER],
      ["for (const k in React) void k;", CARRIER],
      ["void Object.values(React);", CARRIER],
      /* React's module object moved where its type no longer carries act (verifier R7 notExamined: the doc's "any
         value whose type carries React's act" was broader than what was checked), or out of the file, where a
         reader that never names act or react (and so is never scanned) can reach it by a computed key. */
      ['const R: any = React;\nawait R["a" + "ct"](async () => {});', CARRIER],
      ['const R = React as any;\nawait R["a" + "ct"](async () => {});', CARRIER],
      ['let R;\nR = React;\nvoid R;', CARRIER],
      ["(globalThis as any).R = React;", CARRIER],
      ['const getR = () => React;\nconst k4 = String(1) as keyof typeof React;\nvoid getR()[k4];', CARRIER],
      ["export const R5 = React;", CARRIER],
      ["export default React;", CARRIER],
      ["export { React as R6 };", CARRIER],
      ['export * from "react";', CARRIER],
      ['export * as R7 from "react";', CARRIER],
      ['const k5 = "a" + "ct";\nawait require("react")[k5](async () => {});', CARRIER],
      ['const c = String(1) === "1";\nconst R8 = c ? React : {};\nvoid R8;', CARRIER],
      /* A vi.mock factory of React hands the module back to React's own name, and is followed no further — but one
         that REPLACES act there replaces it where no type describes the replacement. */
      [
        'import { vi } from "vitest";\nvi.mock("react", async (importOriginal) => {\n  const m = await importOriginal<typeof import("react")>();\n  return { ...m, act: async () => {} };\n});\nexport {};',
        MOCKED,
      ],
      [
        'import { vi } from "vitest";\nvi.mock("react", async (importOriginal) => {\n  const m = await importOriginal<typeof import("react")>();\n  const act = (): void => {};\n  return { ...m, act };\n});\nexport {};',
        MOCKED,
      ],
      ['import { vi } from "vitest";\nvi.mock("react", () => ({ act() { return Promise.resolve(); } }));\nexport {};', MOCKED],
      /* A factory of some OTHER module does not hand React's module back to React's name. */
      [
        'import { vi } from "vitest";\nvi.mock("./elsewhere", async () => {\n  const m = await import("react");\n  return { ...m };\n});\nexport {};',
        CARRIER,
      ],
      /* R7-V2-1: React's act aliased by a TypeScript import-equals (`import a2 = React.act`): no binding syntax the
         scan listed, so the plainest raw async scope there is passed. Decided by symbol now, not by a list of names. */
      ['import * as React from "react";\nimport a2 = React.act;\nawait a2(async () => {});', VALUE],
      ['import * as React from "react";\nexport import a3 = React.act;', VALUE],
      /* R7-V2-3: a literal holding React's module handed to a call, where the parameter does not type its act. */
      ["Object.assign(globalThis, { R: React });", CARRIER],
      ['Object.defineProperty(globalThis, "R", { value: React });', CARRIER],
      ['const m = new Map([["R", React]]);\nawait (m.get("R") as any)["a" + "ct"](async () => {});', CARRIER],
      /* ...a vi.mock factory of React passed by NAME, or in Vitest's import() form, that replaces act... */
      ['import { vi } from "vitest";\nconst factory = () => ({ act: async () => {} });\nvi.mock("react", factory);\nexport {};', MOCKED],
      ['import { vi } from "vitest";\nvi.mock(import("react"), () => ({ act: async () => {} }));\nexport {};', MOCKED],
      /* ...and React required through a template literal. */
      ['const R11 = require(`react`);\nawait R11["a" + "ct"](async () => {});', CARRIER],
      /* Look-alikes: a Promise-returning function standing in for a library member declared void. (The spies below
         replace `click`, not `focus`: every planted text is ONE program, and a spy voids the member's proofs
         program-wide (R7-V2-2), as at run time — `focus` is what the FINE shapes prove.) */
      [
        'import { act } from "react";\nimport type { Root } from "react-dom/client";\nconst root: Root = { render: async () => {}, unmount() {} };\nact(() => root.render(null));\nexport {};',
        LOOKALIKE,
      ],
      [
        'import { act } from "react";\nimport { vi } from "vitest";\nvi.spyOn(document.body, "click").mockImplementation(async () => {});\nact(() => document.body.click());\nexport {};',
        LOOKALIKE,
      ],
      [
        'import { act } from "react";\nimport type { Root } from "react-dom/client";\nconst root: Root = { async render() {}, unmount() {} };\nact(() => root.render(null));\nexport {};',
        LOOKALIKE,
      ],
      [
        'import { act } from "react";\nimport { vi } from "vitest";\nvi.spyOn(document.body, "click").mockResolvedValue(undefined as never);\nact(() => document.body.click());\nexport {};',
        LOOKALIKE,
      ],
      [
        'import { act } from "react";\nimport { vi } from "vitest";\nvi.spyOn(document.body, "click").mockReturnValue(Promise.resolve() as unknown as void);\nact(() => document.body.click());\nexport {};',
        LOOKALIKE,
      ],
      ['document.body.focus = async () => {};\nact(() => document.body.focus());', LOOKALIKE],
      [
        'import { act } from "react";\nimport type { Root } from "react-dom/client";\nclass FakeRoot implements Root {\n  async render(): Promise<void> {}\n  unmount(): void {}\n}\nconst root: Root = new FakeRoot();\nact(() => root.render(null));\nexport {};',
        LOOKALIKE,
      ],
    ];
  const FINE = [
      "await actAsync(async () => { await flush(); });",
      'import { createRoot } from "react-dom/client";\nimport { act } from "react";\nconst root = createRoot(document.createElement("div"));\nconst ui = null;\nact(() => root.render(ui));',
      "await flushTurns(10, 3);",
      "// await act(async () => {}) in a comment",
      'const s = "await act(async () => {})";',
      "const re = /await act\\(async/;",
      "const t = `await act(async () => {}) ${1}`;",
      /* A journey's own act(), not React's: a member of something that is not React. */
      "const j = { act: async (_p: unknown, _n: number): Promise<number> => 1 };\nconst page = {};\nawait j.act(page, 0).catch(() => null);",
      /* The owner's rule, and React's: a callback PROVED non-thenable closes its scope before act()
         returns, so what the caller does with the result cannot hold the depth. */
      "function set(_n: number): void {}\nawait act(() => set(1));",
      "function set(_n: number): void {}\nconst rerender = () => act(() => set(2));\nrerender();",
      'const bump = (): void => { document.title = "x"; };\nact(() => bump());',
      "function inner(): void {}\nfunction outer(): void { return inner(); }\nact(() => outer());",
      /* The fix the gate names at a flagged site: a block returns undefined, whatever it calls. */
      "const store = { set(_n: number): void {} };\nact(() => { store.set(1); });",
      "const pick: () => void = async () => {};\nact(() => { pick(); });",
      "const pick: () => void = async () => {};\nact(() => void pick());",
      'act(() => { document.body.dispatchEvent(new Event("x")); });',
      'act(() => document.body.dispatchEvent(new Event("x")));',
      'act(() => document.body.focus());',
      /* A library signature that WRITES `void` (not a type parameter) is the library's contract, generic or not. */
      "act(() => [1, 2].forEach(() => {}));",
      "act(() => {});",
      'act(function () { document.title = "x"; });',
      'import { act as flushReact } from "react";\nflushReact(() => {});',
      "type Act = typeof act;\nconst n: Act | null = null;\nvoid n;",
      "const n = 1;\nact(() => n);",
      "act((): any => 1);",
      'act(() => { throw new Error("x"); });',
      'let flag = false;\nact(() => (flag = true));',
      'const n = 2;\nact(() => (n > 1 ? "a" : null));',
      /* A value that carries React's act, read by name or spread into another typed object: still typed, so still judged. */
      "const R2 = React;\nR2.act(() => {});",
      "const m = { ...React, extra: 1 };\nvoid m.useState;",
      "void React.useState;",
      /* Moved without leaving typing: into a typed local, a literal that still types it, or a checked choice. */
      "const box = { R: React, n: 1 };\nvoid box.R.useState;",
      "const all2 = [React] as const;\nvoid all2[0].useState;",
      'const c2 = String(1) === "1";\nconst R9 = c2 ? React : null;\nvoid R9?.useState;',
      "const R10 = (React);\nvoid typeof R10;",
      /* A vi.mock factory of React that hands its module back with act untouched (CommandPalette.test.tsx's shape). */
      'import { vi } from "vitest";\nvi.mock("react", async (importOriginal) => {\n  const m = await importOriginal<typeof import("react")>();\n  const startTransition: typeof m.startTransition = (cb) => m.startTransition(cb);\n  return { ...m, startTransition };\n});\nexport {};',
      /* A Promise-returning function in a slot that is not a library member declared void: an event
         listener, and React's handler types (a method of an anonymous type literal, `bivarianceHack`). */
      'document.body.addEventListener("click", async () => {});',
      'import type { MouseEventHandler } from "react";\nconst onClick: MouseEventHandler = async () => {};\nvoid onClick;\nexport {};',
    ];

  /* Every planted text is a virtual file of ONE program, built once here (the same indivisible unit as the
     tree's, sharing its parsed files; see PROGRAM_BUILD_LIMIT). Each shape is then its own case, so no case
     carries the checking of all of them. */
  let planted: { scan: Scan; offenders: (i: number) => string[] } | undefined;
  beforeAll(() => {
    const { program, files } = plantedProgram("act-planted", [...RAW.map(([t]) => withPreamble(t)), ...FINE.map(withPreamble)]);
    const s = scanOf(program);
    planted = { scan: s, offenders: (i) => offendersIn(s, files[i]!) };
  }, PROGRAM_BUILD_LIMIT);
  const plantedNow = (): NonNullable<typeof planted> => {
    if (planted === undefined) throw new Error("the planted program was not built (beforeAll failed)");
    return planted;
  };

  it("the planted shapes are read against the very React the tree is judged against", () => {
    expect(plantedNow().scan.act.declarations?.[0], "a planted program resolves the same React act").toBe(scanned().act.declarations?.[0]);
    expect(new Set([...RAW.map(([t]) => t), ...FINE]).size, "a planted shape is listed twice").toBe(RAW.length + FINE.length);
  });

  describe("the gate is live — it flags every raw shape, for its own reason", () => {
    it.each(RAW.map(([t, why], i) => [t, why, i] as const))("%s", (t, why, i) => {
      const found = plantedNow().offenders(i);
      expect(found, t).not.toEqual([]);
      expect(found.join("\n"), t).toMatch(why);
    });
  });

  describe("the gate passes what is proved synchronous, and what is not React's act", () => {
    it.each(FINE.map((t, i) => [t, RAW.length + i] as const))("%s", (t, i) => {
      expect(plantedNow().offenders(i), t).toEqual([]);
    });
  });

  /* R7-V2-2 (independent verifier): Vitest's mocks defeat a void-call proof. A project function is proved from its
     own body because "the value called IS that function" — until `vi.mock` or `vi.spyOn` replaces it at run time; and
     a library member's `void` is trusted because every look-alike is reported — but only in files the text prefilter
     read, so a spy installed in a helper that never names act or react was never seen. Each scenario is its OWN
     program (a mock anywhere in a program voids the proofs it replaces everywhere in it, as a spy on a shared object
     does at run time), made of virtual modules under src/core/<scenario>/. */
  const MOCK = /can be replaced by a Vitest mock|mocks a module the scan cannot resolve/;
  const HANDLER = "export const handler = (): void => {};\n";
  const SLOW = "() => new Promise<void>((r) => setTimeout(r, 50))";
  const SCENARIOS: { name: string; files: Record<string, string>; judged: string[]; expect: RegExp | null }[] = [
    {
      name: "a project function replaced by vi.mock in the same file",
      files: { "H.ts": HANDLER, "T.test.tsx": `import { act } from "react";\nimport { vi } from "vitest";\nimport { handler } from "./H";\nvi.mock("./H", () => ({ handler: ${SLOW} }));\nact(() => handler());\n` },
      judged: ["T.test.tsx"],
      expect: MOCK,
    },
    {
      name: "a project function replaced by vi.spyOn(namespace, name)",
      files: { "H.ts": HANDLER, "T.test.tsx": `import { act } from "react";\nimport { vi } from "vitest";\nimport * as H from "./H";\nvi.spyOn(H, "handler").mockImplementation(${SLOW});\nact(() => H.handler());\n` },
      judged: ["T.test.tsx"],
      expect: MOCK,
    },
    {
      name: "a library member spied on in a helper that never names act or react",
      files: {
        "S.ts": `import { vi } from "vitest";\nexport const stubFocus = (): void => {\n  vi.spyOn(document.body, "focus").mockImplementation((${SLOW}) as unknown as () => void);\n};\n`,
        "T.test.tsx": 'import { act } from "react";\nimport { stubFocus } from "./S";\nstubFocus();\nact(() => document.body.focus());\n',
      },
      judged: ["T.test.tsx"],
      expect: MOCK,
    },
    {
      name: "a mock whose module the scan cannot resolve voids the proofs in its file",
      files: { "H.ts": HANDLER, "T.test.tsx": 'import { act } from "react";\nimport { vi } from "vitest";\nimport { handler } from "./H";\nconst spec = String(1);\nvi.doMock(spec, () => ({}));\nact(() => handler());\n' },
      judged: ["T.test.tsx"],
      expect: MOCK,
    },
    {
      name: "CONTROL: the same project function, not mocked, is proved",
      files: { "H.ts": HANDLER, "T.test.tsx": 'import { act } from "react";\nimport { handler } from "./H";\nact(() => handler());\n' },
      judged: ["T.test.tsx"],
      expect: null,
    },
    {
      name: "CONTROL: an automock (no factory: every export a vi.fn() returning undefined) leaves the proof",
      files: { "H.ts": HANDLER, "T.test.tsx": 'import { act } from "react";\nimport { vi } from "vitest";\nimport { handler } from "./H";\nvi.mock("./H");\nact(() => handler());\n' },
      judged: ["T.test.tsx"],
      expect: null,
    },
    {
      name: "CONTROL: the block form needs no proof, mocked or not",
      files: { "H.ts": HANDLER, "T.test.tsx": `import { act } from "react";\nimport { vi } from "vitest";\nimport { handler } from "./H";\nvi.mock("./H", () => ({ handler: ${SLOW} }));\nact(() => { handler(); });\n` },
      judged: ["T.test.tsx"],
      expect: null,
    },
  ];
  let scenarioScans: Map<string, { scan: Scan; files: Map<string, ts.SourceFile> }> | undefined;
  beforeAll(() => {
    scenarioScans = new Map();
    SCENARIOS.forEach((s, k) => {
      const dir = resolve(SRC, "core", `act-mock-scenario-${k}`);
      const paths = new Map(Object.entries(s.files).map(([name, text]) => [resolve(dir, name), text]));
      const program = ts.createProgram([...paths.keys()], OPTIONS, hostWith(paths));
      scenarioScans!.set(s.name, { scan: scanOf(program), files: new Map(Object.keys(s.files).map((name) => [name, program.getSourceFile(resolve(dir, name))!])) });
    });
  }, PROGRAM_BUILD_LIMIT);

  describe("a Vitest mock voids the proof of whatever it replaces, wherever the mock is installed", () => {
    it.each(SCENARIOS.map((s) => [s.name, s] as const))("%s", (_name, s) => {
      const built = scenarioScans?.get(s.name);
      if (built === undefined) throw new Error("the scenario programs were not built (beforeAll failed)");
      for (const f of s.judged) {
        const found = offendersIn(built.scan, built.files.get(f)!);
        if (s.expect === null) expect(found, `${s.name}: ${f}:\n${found.join("\n")}`).toEqual([]);
        else expect(found.join("\n"), `${s.name}: ${f}`).toMatch(s.expect);
      }
    });
  });
});

/* ── no test or hook carries a time limit below the configured hang detector (acceptance F2, load) ─
 * vitest.config.ts sets `testTimeout`/`hookTimeout` as a HANG detector and states the rule a unit
 * test lives by: it asserts no wall-clock time. A per-call limit BELOW that detector is a
 * wall-clock assertion under another name — the test goes red when the host is busy, not when the
 * code regressed. Three files carried one (`{ timeout: 15000 }` / `{ timeout: 20000 }` on whole-App
 * mounts in reaim-tab-and-restore, selection-origin and surfaces), and on both loaded F2 runs they
 * were the only red in the F2-owned files. Limits ABOVE the detector stay each owner's to justify
 * (the config says so); limits below it are not a choice this suite offers. The detector values are
 * read from the config itself, failing closed if they move out of reach.
 *
 * THE CLASS, derived rather than listed. A limit is anything a Vitest function takes as one, and the
 * functions are found in Vitest's own typings by the checker: every call signature declared there
 * with a parameter named for a timeout, or an options parameter carrying an optional `timeout`,
 * `testTimeout` or `hookTimeout` (it/test/describe/suite and their modifiers, every hook,
 * onTestFinished/onTestFailed, vi.setConfig, vi.waitFor/waitUntil, expect.poll). Which calls are read
 * is found by syntax and decided by the checker: a call through a derived function's own name (an
 * export, a member — `.skip`, `.setConfig`, `.onTestFinished`, `.poll` — a namespace member), through a
 * name an import from Vitest binds, through a local bound from one of those (`const t = it`, `const v =
 * vi`, `const { setConfig: s } = vi`), or through a parameter of a function handed to one (the test
 * context's `onTestFinished`); the checker then resolves each to Vitest's declaration. Such a function
 * leaving those names any other way is reported where it leaves (below), so these are all the calls.
 * At each position where any overload takes a limit, an argument that
 * is not a function is a limit, and it must be one this scan can EVALUATE: a number, constant
 * arithmetic, an enum member, a `const` bound to one (in any module), or an options object — a literal,
 * or a `const` object used nowhere else in its file — whose limit keys it can evaluate and which
 * has no spread and no computed key. Anything else is reported. `timeout`/positional limits are held
 * to the larger detector (which of the two governs a given call is not in the typings), `testTimeout`
 * and `hookTimeout` to their own. A waiting function (vi.waitFor/waitUntil, expect.poll) left without
 * a limit uses Vitest's own default (1 s), not the detector, so it is reported too.
 *
 * FAILING CLOSED where the checker cannot follow (verifier findings F2-R2-2 and R7-V2): a Vitest
 * limit-taking function (or a local alias of one) used as a value anywhere but as the thing called,
 * the root of a chain whose next link is Vitest's own, a template tag, or the initializer of a typed
 * alias (`.call`, `Reflect.apply`, an argument, a variable typed `any`, `(it as any)`); a computed key, a computed destructuring key or a `for…in`
 * on a Vitest object that carries one; such an object passed where the parameter does not type it as
 * one; a call through an untyped value (`globalThis.it`, `require("vitest")`) whose NAME is one of the
 * derived functions, read by name, and a call through an untyped modifier CALL chained on one
 * (`(globalThis as any).it.each(t)(…)`, which has no name of its own: verifier finding R7-V8), read by
 * every derived name on its chain; a local bound from a derived function under ANOTHER name from an untyped
 * value (`const { it: x } = globalThis as any`), or a typed alias of an untyped read (`const x: typeof it =
 * (globalThis as any).it`), read at the positions of the name it was bound from, and an untyped call through
 * such a name that nothing resolves reported (verifier finding R7-V2-4); an options object written to, or handed anywhere, before it is
 * read. The files read are every source under src/ — the tests, the setupFiles vitest.config.ts
 * names (read from the config, not assumed), and every module they can call into. */
describe("no test or hook sets a time limit below the configured hang detector", () => {
  const configText = readFileSync(resolve(ROOT, "vitest.config.ts"), "utf8");
  const configSource = parseAs(configText, "vitest.config.ts");
  const configured = (key: string): number | null => {
    let found: number | null = null;
    const visit = (n: ts.Node): void => {
      if (ts.isPropertyAssignment(n) && ts.isIdentifier(n.name) && n.name.text === key && ts.isNumericLiteral(n.initializer)) {
        found = Number(n.initializer.text.replace(/_/g, ""));
      }
      ts.forEachChild(n, visit);
    };
    visit(configSource);
    return found;
  };
  const TEST_LIMIT = configured("testTimeout");
  const HOOK_LIMIT = configured("hookTimeout");
  /** The files vitest.config.ts loads through `setupFiles`, repo-relative; null when an entry cannot be read. */
  const SETUP_FILES = ((): string[] | null => {
    let entries: readonly ts.Expression[] | null = null;
    const visit = (n: ts.Node): void => {
      if (ts.isPropertyAssignment(n) && ts.isIdentifier(n.name) && n.name.text === "setupFiles") entries = ts.isArrayLiteralExpression(n.initializer) ? n.initializer.elements : [];
      ts.forEachChild(n, visit);
    };
    visit(configSource);
    if (entries === null) return null;
    const out: string[] = [];
    for (const e of entries as readonly ts.Expression[]) {
      const literals: string[] = [];
      const find = (n: ts.Node): void => {
        if (ts.isStringLiteralLike(n)) literals.push(n.text);
        ts.forEachChild(n, find);
      };
      find(e);
      if (literals.length !== 1) return null;
      out.push(rel(resolve(ROOT, literals[0]!)));
    }
    return out;
  })();

  const LIMIT_KEY = /^(?:timeout|testTimeout|hookTimeout)$/;
  const VITEST_MODULE = /^(?:vitest|@vitest\/[^/]+)(?:\/.*)?$/;
  const VITEST_SPECIFIER = /["'](?:vitest|@vitest\/[^"'/]+)(?:\/[^"']*)?["']/;
  /* The waiting functions: a limit left out is Vitest's own default, not the detector. Which of the
     derived functions wait is not in their typings, so the derived set is pinned below to exactly the
     functions each list here classifies — a Vitest that adds one fails that pin until it is classified. */
  const WAITERS = new Set(["waitFor", "waitUntil", "poll"]);
  const REGISTRARS = new Set([
    ...["it", "test", "describe", "suite", "beforeEach", "afterEach", "beforeAll", "afterAll", "aroundEach", "aroundAll", "onTestFinished", "onTestFailed"],
    ...["concurrent", "sequential", "only", "skip", "todo", "fails", "shuffle"],
  ]);
  const CONFIG = new Set(["setConfig"]);

  interface Api {
    program: ts.Program;
    checker: ts.TypeChecker;
    /** Whether a value of this type is a Vitest function that takes a time limit. */
    takesLimit(t: ts.Type): boolean;
    /** The argument positions where any overload of a value of this type takes a limit. */
    limitPositions(t: ts.Type): Set<number>;
    /** Whether a value of this type is a Vitest object with a member that takes a limit. */
    vitestCarrier(t: ts.Type): boolean;
    /** Every derived limit-taking function, by the name it is reached by, with its limit positions. */
    byName: Map<string, Set<number>>;
    fromVitest(n: ts.Node | undefined): boolean;
  }
  const apiOf = (program: ts.Program): Api => {
    const checker = program.getTypeChecker();
    const fromVitest = (n: ts.Node | undefined): boolean => n !== undefined && VITEST_TYPINGS.test(n.getSourceFile().fileName);
    const parts = (t: ts.Type): readonly ts.Type[] => (t.isUnion() || t.isIntersection() ? t.types : [t]);
    const hasLimitKey = (t: ts.Type): boolean =>
      parts(t).some((u) => checker.getPropertiesOfType(u).some((p) => LIMIT_KEY.test(p.name) && (p.flags & ts.SymbolFlags.Optional) !== 0));
    const paramType = (p: ts.Symbol): ts.Type => checker.getNonNullableType(checker.getTypeOfSymbol(p));
    const namedLimit = (p: ts.Symbol): boolean => /timeout/i.test(p.name) || hasLimitKey(paramType(p));
    /* Within a limit-taking function a number parameter is a limit too (`it(name, fn, options: number)`). */
    const limitParam = (p: ts.Symbol): boolean => namedLimit(p) || parts(paramType(p)).some((u) => (u.flags & ts.TypeFlags.NumberLike) !== 0);
    const vitestSignatures = (t: ts.Type): ts.Signature[] =>
      (t.flags & (ts.TypeFlags.Any | ts.TypeFlags.Unknown)) !== 0 ? [] : parts(t).flatMap((u) => u.getCallSignatures()).filter((s) => fromVitest(s.declaration));
    const takes = new Map<ts.Type, boolean>();
    const takesLimit = (t: ts.Type): boolean => {
      let v = takes.get(t);
      if (v === undefined) takes.set(t, (v = vitestSignatures(t).some((s) => s.getParameters().some(namedLimit))));
      return v;
    };
    const limitPositions = (t: ts.Type): Set<number> => {
      const out = new Set<number>();
      if (!takesLimit(t)) return out;
      for (const s of vitestSignatures(t)) s.getParameters().forEach((p, i) => limitParam(p) && out.add(i));
      return out;
    };
    const vitestCarrier = (t: ts.Type): boolean =>
      (t.flags & (ts.TypeFlags.Any | ts.TypeFlags.Unknown)) === 0 &&
      parts(t).some((u) => [u.symbol, u.aliasSymbol].some((s) => s?.declarations?.some(fromVitest) === true)) &&
      checker.getPropertiesOfType(checker.getApparentType(t)).some((p) => takesLimit(checker.getTypeOfSymbol(p)));

    /* The derived set: Vitest's exports, their members, and the test context's members. */
    const byName = new Map<string, Set<number>>();
    const note = (name: string, t: ts.Type): void => {
      if (!takesLimit(t)) return;
      const at = byName.get(name) ?? new Set<number>();
      for (const i of limitPositions(t)) at.add(i);
      byName.set(name, at);
    };
    const typings = ts.resolveModuleName("vitest", resolve(SRC, "main.tsx"), OPTIONS, ts.sys).resolvedModule?.resolvedFileName;
    const moduleFile = typings === undefined ? undefined : program.getSourceFile(typings);
    const moduleSymbol = moduleFile === undefined ? undefined : checker.getSymbolAtLocation(moduleFile);
    if (moduleSymbol === undefined) throw new Error(`Vitest's typings could not be read through "vitest" (typings: ${typings ?? "unresolved"})`);
    for (const exported of checker.getExportsOfModule(moduleSymbol)) {
      const s = exported.flags & ts.SymbolFlags.Alias ? checker.getAliasedSymbol(exported) : exported;
      if (exported.name === "TestContext") {
        for (const p of checker.getPropertiesOfType(checker.getDeclaredTypeOfSymbol(s))) {
          const pt = checker.getTypeOfSymbol(p);
          note(p.name, pt);
          for (const q of checker.getPropertiesOfType(pt)) note(q.name, checker.getTypeOfSymbol(q));
        }
      }
      if ((s.flags & ts.SymbolFlags.Value) === 0) continue;
      const t = checker.getTypeOfSymbol(s);
      note(exported.name, t);
      for (const p of checker.getPropertiesOfType(t)) note(p.name, checker.getTypeOfSymbol(p));
    }
    return { program, checker, takesLimit, limitPositions, vitestCarrier, byName, fromVitest };
  };

  let api: Api | undefined;
  const apiNow = (): Api => {
    if (api === undefined) throw new Error("the program was not built (beforeAll failed)");
    return api;
  };
  beforeAll(() => {
    api = apiOf(treeProgram());
  }, PROGRAM_BUILD_LIMIT);

  const unwrap = (e: ts.Expression): ts.Expression =>
    ts.isParenthesizedExpression(e) || ts.isSatisfiesExpression(e) || ts.isNonNullExpression(e) ? unwrap(e.expression) : e;

  /** Each limit below the detector, and each limit it cannot read, in one file, as `line: <what>`. */
  /** What the guard read: the calls it held to a limit, over the files it scanned. */
  interface Read {
    files: number;
    held: number;
  }
  const lowLimits = (a: Api, sf: ts.SourceFile, testLimit: number, hookLimit: number, tally?: Read): string[] => {
    if (tally !== undefined) tally.files += 1;
    const { checker } = a;
    const out: string[] = [];
    const lineOf = (n: ts.Node): number => sf.getLineAndCharacterOfPosition(n.getStart(sf)).line + 1;
    const limitFor = (key: string): number => (key === "testTimeout" ? testLimit : key === "hookTimeout" ? hookLimit : Math.max(testLimit, hookLimit));
    const symbolOf = (n: ts.Node): ts.Symbol | undefined => {
      const s = checker.getSymbolAtLocation(n);
      return s !== undefined && s.flags & ts.SymbolFlags.Alias ? checker.getAliasedSymbol(s) : s;
    };
    /* `any` (and an unresolved name's error type, which is `any`): the checker cannot say what it is. */
    const anyTyped = (t: ts.Type): boolean => (t.flags & ts.TypeFlags.Any) !== 0;
    /** The `const` declaration `id` refers to (in any module), or null for a `let`, a parameter, an unresolved name. */
    const constOf = (id: ts.Identifier): ts.VariableDeclaration | null => {
      const p = id.parent;
      const d = (ts.isShorthandPropertyAssignment(p) && p.name === id ? checker.getShorthandAssignmentValueSymbol(p) : symbolOf(id))?.valueDeclaration;
      return d !== undefined && ts.isVariableDeclaration(d) && d.initializer !== undefined && (d.parent.flags & ts.NodeFlags.Const) !== 0 ? d : null;
    };

    /** The number `e` evaluates to, or null when that cannot be read here. */
    const evaluate = (e: ts.Expression, depth = 0): number | null => {
      if (depth > 20) return null;
      const x = unwrap(ts.isAsExpression(e) || ts.isTypeAssertionExpression(e) ? e.expression : e);
      if (ts.isNumericLiteral(x)) return Number(x.text.replace(/_/g, ""));
      if (ts.isPrefixUnaryExpression(x) && (x.operator === ts.SyntaxKind.MinusToken || x.operator === ts.SyntaxKind.PlusToken)) {
        const v = evaluate(x.operand, depth + 1);
        return v === null ? null : x.operator === ts.SyntaxKind.MinusToken ? -v : v;
      }
      if (ts.isBinaryExpression(x)) {
        const l = evaluate(x.left, depth + 1);
        const r = evaluate(x.right, depth + 1);
        if (l === null || r === null) return null;
        switch (x.operatorToken.kind) {
          case ts.SyntaxKind.PlusToken: return l + r;
          case ts.SyntaxKind.MinusToken: return l - r;
          case ts.SyntaxKind.AsteriskToken: return l * r;
          case ts.SyntaxKind.SlashToken: return l / r;
          case ts.SyntaxKind.AsteriskAsteriskToken: return l ** r;
          default: return null;
        }
      }
      if (ts.isPropertyAccessExpression(x)) {
        /* An enum member, evaluated from its own initializer. */
        const member = symbolOf(x.name)?.valueDeclaration;
        return member !== undefined && ts.isEnumMember(member) && member.initializer !== undefined ? evaluate(member.initializer, depth + 1) : null;
      }
      if (ts.isIdentifier(x)) {
        const d = constOf(x);
        return d === null ? null : evaluate(d.initializer!, depth + 1);
      }
      return null;
    };

    /** Where the options object bound to `d` is used other than as a held limit argument: a way for its limit to change before it is read. */
    const escapes = (d: ts.VariableDeclaration): string[] => {
      const declared = d.name;
      if (d.getSourceFile() !== sf || !ts.isIdentifier(declared)) return ["it is declared in another module"];
      const symbol = checker.getSymbolAtLocation(declared);
      const uses: string[] = [];
      const visit = (n: ts.Node): void => {
        if (ts.isIdentifier(n) && n !== declared && n.text === declared.text && checker.getSymbolAtLocation(n) === symbol) {
          const p = n.parent;
          const held = ts.isCallExpression(p) && p.arguments.includes(n) && heldCall(p);
          if (!held) uses.push(`${lineOf(n)}: ${brief(p)}`);
        }
        ts.forEachChild(n, visit);
      };
      visit(sf);
      return uses;
    };
    /** Hold every limit key of an options object; a spread or a computed key is not readable. Returns whether it named a limit. */
    const holdOptions = (label: string, obj: ts.ObjectLiteralExpression): boolean => {
      let named = false;
      for (const p of obj.properties) {
        if (ts.isSpreadAssignment(p)) {
          out.push(`${lineOf(p)}: ${label} options spread ${brief(p)}; the limit it carries cannot be read`);
          continue;
        }
        const key = p.name === undefined ? null : ts.isIdentifier(p.name) || ts.isStringLiteralLike(p.name) || ts.isNumericLiteral(p.name) ? p.name.text : null;
        if (key === null) {
          out.push(`${lineOf(p)}: ${label} options key ${brief(p)} cannot be read`);
          continue;
        }
        if (!LIMIT_KEY.test(key)) continue;
        named = true;
        if (ts.isPropertyAssignment(p)) holdNumber(label, p.initializer, limitFor(key));
        else if (ts.isShorthandPropertyAssignment(p)) holdNumber(label, p.name, limitFor(key));
        else out.push(`${lineOf(p)}: ${label} ${key} is not a value it can read`);
      }
      return named;
    };
    const holdNumber = (label: string, v: ts.Expression, limit: number): void => {
      const value = evaluate(v);
      if (value === null) out.push(`${lineOf(v)}: ${label} limit is not a number it can read (${brief(v)})`);
      else if (!(value >= limit)) out.push(`${lineOf(v)}: ${label} ${brief(v)} < ${limit}`);
    };
    /** Hold one argument at a limit position. Returns whether it supplied a limit. */
    const holdArgument = (label: string, arg: ts.Expression): boolean => {
      const x = unwrap(arg);
      if (ts.isSpreadElement(x)) {
        out.push(`${lineOf(x)}: ${label} arguments spread; the limit they carry cannot be read`);
        return true;
      }
      const t = checker.getTypeAtLocation(x);
      if (!anyTyped(t) && t.getCallSignatures().length > 0) return false; // a callback, at a position an overload gives one
      if (ts.isObjectLiteralExpression(x)) return holdOptions(label, x);
      const d = ts.isIdentifier(x) ? constOf(x) : null;
      if (d !== null && ts.isObjectLiteralExpression(unwrap(d.initializer!))) {
        const uses = escapes(d);
        if (uses.length > 0) out.push(`${lineOf(x)}: ${label} options object ${brief(x)} is also used elsewhere, so its limit can change before it is read (${uses.join("; ")})`);
        return holdOptions(label, unwrap(d.initializer!) as ts.ObjectLiteralExpression);
      }
      holdNumber(label, x, limitFor("timeout"));
      return true;
    };
    /** The name a callee is reached by: `it`, `vi.setConfig` → `setConfig`, `x["poll"]` → `poll`. */
    const calleeName = (e: ts.Expression): string | null => {
      const x = unwrap(e);
      if (ts.isIdentifier(x)) return x.text;
      if (ts.isPropertyAccessExpression(x)) return x.name.text;
      if (ts.isElementAccessExpression(x) && ts.isStringLiteralLike(x.argumentExpression)) return x.argumentExpression.text;
      return null;
    };
    /** Every name along a callee's chain, through calls and member reads: `g.it.each(t)` → `each`, `it`, `g`. */
    const chainNames = (e: ts.Expression): string[] => {
      const out: string[] = [];
      for (let x: ts.Expression = unwrap(e); ; ) {
        if (ts.isAsExpression(x) || ts.isTypeAssertionExpression(x)) x = unwrap(x.expression);
        else if (ts.isCallExpression(x)) x = unwrap(x.expression);
        else if (ts.isPropertyAccessExpression(x)) {
          out.push(x.name.text);
          x = unwrap(x.expression);
        } else if (ts.isElementAccessExpression(x)) {
          if (ts.isStringLiteralLike(x.argumentExpression)) out.push(x.argumentExpression.text);
          x = unwrap(x.expression);
        } else {
          if (ts.isIdentifier(x)) out.push(x.text);
          return out;
        }
      }
    };
    /** The limit positions of a call the guard reads, or null for any other call. A Vitest limit-taking function by
        its type; an untyped callee NAMED as one by that name; and an untyped callee that is itself a call — a modifier
        chained on an untyped value (`(globalThis as any).it.each(t)(…)`, verifier finding R7-V8), which has no name
        of its own — by every derived name along its chain, so it is read as the function it was chained from. */
    const heldPositions = (call: ts.CallExpression): Set<number> | null => {
      const t = checker.getTypeAtLocation(call.expression);
      if (a.takesLimit(t)) return a.limitPositions(t);
      if (!anyTyped(t)) return null;
      const name = calleeName(call.expression);
      if (name !== null && a.byName.has(name)) return a.byName.get(name)!;
      /* A local bound from a derived function under ANOTHER name, from an untyped value (R7-V2-4:
         `const { it: x } = globalThis as any`): held at the positions of the name it was bound from. */
      const bound = name === null ? undefined : derivedKey.get(name);
      if (bound !== undefined) return a.byName.get(bound)!;
      const derived = chainNames(call.expression).filter((n) => a.byName.has(n));
      if (derived.length === 0) return null;
      return new Set(derived.flatMap((n) => [...a.byName.get(n)!]));
    };
    /** Whether this call is one the guard reads. */
    const heldCall = (call: ts.CallExpression): boolean => heldPositions(call) !== null;

    /* ── candidates, found by syntax: only these are handed to the checker, which then decides ──
       A Vitest limit-taking function reaches code in this file only (a) by its own name — an export, a
       member (`.skip`, `.setConfig`, `.onTestFinished`, `.poll`), a global, or a namespace member; (b) by a
       name an import from Vitest binds; (c) by a local bound from one of those (`const t = it`, `const v =
       vi`, `const { setConfig: s } = vi`, `await import("vitest")`), to a fixpoint; or (d) through the test
       context, a parameter of a function handed to one. Any other flow of such a value out of its name —
       an argument, a return, a property, an assertion — is reported below, so these are all the calls. */
    const candidates = new Set(a.byName.keys());
    /** For a local bound from a derived function, the derived name it was bound from (`x` -> `it`). */
    const derivedKey = new Map<string, string>();
    for (const st of sf.statements) {
      if (!ts.isImportDeclaration(st) || !ts.isStringLiteral(st.moduleSpecifier) || !VITEST_MODULE.test(st.moduleSpecifier.text)) continue;
      const clause = st.importClause;
      if (clause?.name !== undefined) candidates.add(clause.name.text);
      const b = clause?.namedBindings;
      if (b !== undefined && ts.isNamespaceImport(b)) candidates.add(b.name.text);
      if (b !== undefined && ts.isNamedImports(b)) for (const el of b.elements) candidates.add(el.name.text);
    }
    const locals: ts.VariableDeclaration[] = [];
    const handedFunctions: ts.CallExpression[] = [];
    const gather = (n: ts.Node): void => {
      if (ts.isVariableDeclaration(n) && n.initializer !== undefined) locals.push(n);
      if (ts.isCallExpression(n) && n.arguments.some((x) => ts.isArrowFunction(x) || ts.isFunctionExpression(x))) handedFunctions.push(n);
      /* A derived member taken out by destructuring, anywhere (`const { onTestFinished: done } = c`, a
         parameter `({ setConfig: s })`): its local name is a way to the member. */
      if (ts.isBindingElement(n) && ts.isObjectBindingPattern(n.parent)) {
        const key = n.propertyName ?? n.name;
        if ((ts.isIdentifier(key) || ts.isStringLiteral(key)) && a.byName.has(key.text)) {
          for (const name of bindingNames(n.name)) {
            candidates.add(name);
            if (ts.isIdentifier(n.name) && !derivedKey.has(name)) derivedKey.set(name, key.text);
          }
        }
      }
      ts.forEachChild(n, gather);
    };
    gather(sf);
    for (let grew = true; grew; ) {
      grew = false;
      const bind = (names: string[]): void => {
        for (const name of names) {
          if (candidates.has(name)) continue;
          candidates.add(name);
          grew = true;
        }
      };
      for (const d of locals) {
        const root = rootNameOf(d.initializer!);
        if ((root !== null && candidates.has(root)) || VITEST_SPECIFIER.test(d.initializer!.getText(sf))) bind(bindingNames(d.name));
        /* A local whose initializer READS a derived function through a member chain, from whatever root — a typed
           alias of an untyped read (R7-V2-4: `const x: typeof it = (globalThis as any).it`): its calls are read too,
           and, untyped, at the positions of the name the chain reached. */
        const reached = chainNames(d.initializer!).find((n) => a.byName.has(n));
        if (reached !== undefined) {
          bind(bindingNames(d.name));
          if (ts.isIdentifier(d.name) && !derivedKey.has(d.name.text)) derivedKey.set(d.name.text, reached);
        }
      }
      for (const call of handedFunctions) {
        const root = rootNameOf(call.expression);
        if (root === null || !candidates.has(root)) continue;
        for (const x of call.arguments) if (ts.isArrowFunction(x) || ts.isFunctionExpression(x)) for (const p of x.parameters) bind(bindingNames(p.name));
      }
    }
    /** Whether the checker should read the root of `e`: a candidate name, or a parameter (whose value comes from a caller). */
    const readRoot = (e: ts.Expression): boolean => {
      const root = rootIdentifierOf(e);
      return root !== null && (candidates.has(root.text) || checker.getSymbolAtLocation(root)?.valueDeclaration?.kind === ts.SyntaxKind.Parameter);
    };
    /** Whether a call can reach a Vitest limit-taking function, by syntax: `it(…)`, `x.skip(…)`, `x["poll"](…)`, `it.each(t)(…)`. */
    const mayHold = (call: ts.CallExpression): boolean => {
      const callee = unwrap(call.expression);
      if (ts.isIdentifier(callee)) return candidates.has(callee.text);
      if (ts.isPropertyAccessExpression(callee)) return a.byName.has(callee.name.text);
      if (ts.isElementAccessExpression(callee)) return !ts.isStringLiteralLike(callee.argumentExpression) || a.byName.has(callee.argumentExpression.text);
      const root = rootNameOf(callee);
      /* A call whose callee is a call (`x.each(t)(…)`): reachable from a candidate root, or through any derived name on its chain. */
      return (root !== null && candidates.has(root)) || chainNames(callee).some((n) => a.byName.has(n));
    };

    const visit = (n: ts.Node): void => {
      if (ts.isCallExpression(n) && mayHold(n)) {
        const name = calleeName(n.expression) ?? brief(n.expression);
        const positions = heldPositions(n);
        /* FAILING CLOSED (R7-V2-4): an untyped call through a name bound from a Vitest function, whose limit
           positions nothing above could resolve, is reported — never passed as "not a Vitest call". */
        const callee0 = unwrap(n.expression);
        if (positions === null && ts.isIdentifier(callee0) && candidates.has(callee0.text) && !a.byName.has(callee0.text) && anyTyped(checker.getTypeAtLocation(callee0))) {
          out.push(`${lineOf(n)}: ${callee0.text}(…) is an untyped call through a name bound from a Vitest function, and which limit it takes cannot be read`);
        }
        if (positions !== null) {
          if (tally !== undefined) tally.held += 1;
          let supplied = false;
          n.arguments.forEach((arg, i) => {
            if (positions.has(i) || ts.isSpreadElement(arg)) supplied = holdArgument(name, arg) || supplied;
          });
          const callee = unwrap(n.expression);
          const own = symbolOf(ts.isPropertyAccessExpression(callee) ? callee.name : callee);
          if (!supplied && WAITERS.has(own?.name ?? name)) out.push(`${lineOf(n)}: ${name} without a limit waits for Vitest's own default, not the detector`);
        }
      }
      /* A Vitest limit-taking function, or a local alias of one, used other than as the thing called, the
         root of a chain whose next link is Vitest's own (`it.skip`, `it.each`), a template tag, or the
         initializer of another alias: its value leaves the names above, so its calls could not be read. */
      if (ts.isIdentifier(n) && !inTypePosition(n) && !isDeclarationName(n)) {
        const asName = ts.isPropertyAccessExpression(n.parent) && n.parent.name === n;
        const considered = asName ? a.byName.has(n.text) : candidates.has(n.text);
        if (considered) {
          const ref: ts.Expression = asName ? (n.parent as ts.PropertyAccessExpression) : n;
          const s = symbolOf(n);
          const declared = s?.declarations?.some(a.fromVitest) === true;
          const local = !declared && s !== undefined && s.valueDeclaration !== undefined && s.valueDeclaration.getSourceFile() === sf;
          const limitValue =
            (declared && a.takesLimit(checker.getTypeOfSymbol(s!))) ||
            (local && a.takesLimit(checker.getTypeAtLocation(ref))) ||
            ((s === undefined || !declared) && !local && anyTyped(checker.getTypeAtLocation(ref)) && a.byName.has(n.text));
          if (limitValue) {
            let up: ts.Node = ref.parent;
            let at: ts.Node = ref;
            while (ts.isParenthesizedExpression(up) || ts.isNonNullExpression(up)) {
              at = up;
              up = up.parent;
            }
            const called = ts.isCallExpression(up) && up.expression === at;
            const chained =
              ts.isPropertyAccessExpression(up) && up.expression === at && (symbolOf(up.name)?.declarations?.some(a.fromVitest) === true || anyTyped(checker.getTypeAtLocation(up)));
            const tagged = ts.isTaggedTemplateExpression(up) && up.tag === at;
            const aliased = ts.isVariableDeclaration(up) && up.initializer === at && !anyTyped(checker.getTypeAtLocation(up.name));
            const named = ts.isImportSpecifier(up) || ts.isExportSpecifier(up) || ts.isTypeQueryNode(up);
            if (!called && !chained && !tagged && !aliased && !named) {
              out.push(`${lineOf(ref)}: ${brief(ref)} used as a value (${ts.SyntaxKind[up.kind]}), where its calls cannot be read`);
            }
          }
        }
      }
      /* A Vitest object reached by a key the checker cannot resolve, enumerated, or handed where it is not typed as one. */
      if (ts.isElementAccessExpression(n) && !ts.isStringLiteralLike(n.argumentExpression) && !ts.isNumericLiteral(n.argumentExpression) && readRoot(n.expression) && a.vitestCarrier(checker.getTypeAtLocation(n.expression))) {
        out.push(`${lineOf(n)}: a computed key on a Vitest object (${brief(n)}); which function it reaches cannot be read`);
      }
      if (ts.isBindingElement(n) && n.propertyName !== undefined && ts.isComputedPropertyName(n.propertyName) && ts.isObjectBindingPattern(n.parent) && a.vitestCarrier(checker.getTypeAtLocation(n.parent))) {
        out.push(`${lineOf(n)}: a computed key destructured from a Vitest object (${brief(n)}); which function it reaches cannot be read`);
      }
      if (ts.isForInStatement(n) && a.vitestCarrier(checker.getTypeAtLocation(n.expression))) {
        out.push(`${lineOf(n)}: a Vitest object enumerated (${brief(n.expression)}); which function it reaches cannot be read`);
      }
      if ((ts.isCallExpression(n) || ts.isNewExpression(n)) && n.arguments !== undefined) {
        for (const arg of n.arguments) {
          const x = unwrap(ts.isSpreadElement(arg) ? arg.expression : arg);
          if (ts.isFunctionLike(x) || ts.isLiteralExpression(x) || ts.isObjectLiteralExpression(x) || !readRoot(x)) continue;
          if (!a.vitestCarrier(checker.getTypeAtLocation(x))) continue;
          const slot = ts.isSpreadElement(arg) ? undefined : checker.getContextualType(arg);
          if (slot === undefined || !a.vitestCarrier(slot)) out.push(`${lineOf(arg)}: a Vitest object passed to ${brief(n.expression)} where it is no longer typed as one (${brief(arg)})`);
        }
      }
      ts.forEachChild(n, visit);
    };
    const isDeclarationName = (n: ts.Identifier): boolean => {
      const p = n.parent;
      if (ts.isImportSpecifier(p) || ts.isImportClause(p) || ts.isNamespaceImport(p) || ts.isExportSpecifier(p)) return true;
      if (ts.isBindingElement(p)) return p.name === n || p.propertyName === n;
      const named = p as ts.Node & { name?: ts.Node };
      return named.name === n && !ts.isPropertyAccessExpression(p) && !ts.isShorthandPropertyAssignment(p);
    };
    visit(sf);
    return out;
  };

  it("read both hang-detector limits and the setup files from vitest.config.ts", () => {
    expect(TEST_LIMIT, "vitest.config.ts no longer sets testTimeout as a numeric literal").not.toBeNull();
    expect(HOOK_LIMIT, "vitest.config.ts no longer sets hookTimeout as a numeric literal").not.toBeNull();
    expect(SETUP_FILES, "a setupFiles entry of vitest.config.ts could not be read").not.toBeNull();
    expect(SETUP_FILES!.length, "vitest.config.ts names no setup file").toBeGreaterThan(0);
    /* A setup file registers hooks for every test; it must be among the files read, and one the checker reads. */
    for (const f of SETUP_FILES!) {
      expect(codeFiles, `${f} (a setupFiles entry) is not among the files read`).toContain(f);
      expect(CHECKED.test(f), `${f} is not a file the checker reads`).toBe(true);
    }
  });

  it("derived Vitest's limit-taking functions from its typings, and every one is classified", () => {
    /* The class comes from the typings; the classification of each member (does a limit left out mean the
       detector, or Vitest's own default?) cannot, so it is pinned to exactly the derived set. */
    const derived = [...apiNow().byName.keys()].sort();
    expect(derived).toEqual([...REGISTRARS, ...WAITERS, ...CONFIG].sort());
  });

  const read = codeFiles.filter((f) => CHECKED.test(f));
  it("reads every source file the runner can load", () => {
    expect(read.filter((f) => /\.test\.tsx?$/.test(f)).length, "the walk found the suite").toBeGreaterThan(100);
    expect(codeFiles.filter((f) => !CHECKED.test(f)), "a source under src/ the checker does not read").toEqual([]);
  });

  /* One case per file, as for the act scan above. The tally is read by the case after them. */
  const tally: Read = { files: 0, held: 0 };
  describe("every source file the runner can load keeps to them", () => {
    it.each(read)("%s", (f) => {
      const a = apiNow();
      const low = lowLimits(a, a.program.getSourceFile(resolve(ROOT, f))!, TEST_LIMIT!, HOOK_LIMIT!, tally);
      expect(low, `per-call limits below the configured hang detector, or not readable, in ${f} (a wall-clock assertion under load):\n${low.join("\n")}`).toEqual([]);
    });
  });

  it("read real test and hook calls in every file (the class is not empty)", () => {
    /* A candidate filter or a derivation that stopped matching would read nothing and pass every file,
       so what was read is counted: every file visited (run the whole describe, not this case alone), and
       the calls held — the suite registers thousands of tests and hooks. */
    expect(tally.files, "the per-file cases above did not all run").toBe(read.length);
    expect(tally.held, "the guard held no test or hook call").toBeGreaterThan(1000);
  });

  /* Planted texts get Vitest's functions imported unless they import from "vitest" themselves (the suite's
     globals are not typed here, so an un-imported `it` is untyped, and read by its name). */
  const VITEST_PREAMBLE =
    'import { afterAll, afterEach, aroundAll, aroundEach, beforeAll, beforeEach, describe, expect, it, onTestFailed, onTestFinished, suite, test, vi } from "vitest";\n';
  const LOW = [
      'it("x", { timeout: 15000 }, async () => {});',
      'it("x", async () => {}, 15_000);',
      'test.each([1])("x %s", async () => {}, { timeout: 100 });',
      'it.skip("x", { "timeout": 20000 }, () => {});',
      'describe("x", { timeout: 1000 }, () => {});',
      "beforeEach(async () => {}, 5000);",
      'it("x", { timeout: LIMIT }, () => {});',
      'const LIMIT = 10_000;\nit("x", { timeout: LIMIT }, () => {});',
      'const LIMIT = 10_000;\nit("x", async () => {}, LIMIT);',
      /* F2-R2-2: each of these passed the first version. */
      'it("x", async () => {}, 15 * 1000);',
      'const LIMIT = 40_000;\nit("x", async () => {}, LIMIT / 2);',
      "vi.setConfig({ testTimeout: 1000 });",
      "vi.setConfig({ hookTimeout: 1000 });",
      "declare const config: { testTimeout: number };\nvi.setConfig(config);",
      'import { vi as v } from "vitest";\nv.setConfig({ testTimeout: 1000 });',
      'import { it } from "vitest";\nimport { LIMIT } from "./limits";\nit("x", async () => {}, LIMIT);',
      'let LIMIT = 1000;\nit("x", async () => {}, LIMIT);',
      'const opts = { timeout: 1000 };\nit("x", opts, async () => {});',
      'it("x", { ...{ timeout: 1000 } }, async () => {});',
      'const base = { timeout: 60_000 };\nit("x", { ...base }, async () => {});',
      'declare const key: "timeout";\nit("x", { [key]: 1000 }, async () => {});',
      'const timeout = 1000;\nit("x", { timeout }, async () => {});',
      'declare const limits: { short: number };\nit("x", async () => {}, limits.short);',
      'declare function pick(): number;\nit("x", async () => {}, pick());',
      /* Untyped where a limit may stand: it could as well be a limit. */
      'declare const body: any;\nit("x", body);',
      'import { it as check } from "vitest";\ncheck("x", async () => {}, 1000);',
      'const t = it;\nt("x", async () => {}, 1000);',
      'it.skipIf(false)("x", async () => {}, 1000);',
      "afterAll(async () => {}, 1000);",
      'const myIt = it.extend({ page: async ({}, use: (n: number) => Promise<void>) => { await use(1); } });\nmyIt("x", async () => {}, 1000);',
      'const LIMIT = 1;\nconst LIMIT2 = 2;\nfunction f() { const LIMIT = 60_000; return LIMIT; }\nvoid f;\nvoid LIMIT2;\nit("x", async () => {}, LIMIT);',
      /* R7-V2: each of these passed the version before this one. */
      "const v = vi;\nv.setConfig({ testTimeout: 1000 });",
      'vi["setConfig"]({ testTimeout: 1000 });',
      "const { setConfig } = vi;\nsetConfig({ testTimeout: 1000 });",
      'import { vi as v } from "vitest";\nconst w = v;\nw.setConfig({ testTimeout: 1000 });',
      'import * as V from "vitest";\nV.it("x", async () => {}, 1000);',
      'import * as V from "vitest";\nV.vi.setConfig({ testTimeout: 1000 });',
      "onTestFinished(() => {}, 1000);",
      'import { onTestFailed } from "vitest";\nonTestFailed(() => {}, 1000);',
      'it("x", async ({ onTestFinished }) => { onTestFinished(() => {}, 1000); });',
      'it("x", async (ctx) => { ctx.onTestFinished(() => {}, 1000); });',
      /* A helper handed the context, taking the member out under another name. */
      'import type { TestContext } from "vitest";\nconst later = (c: TestContext): void => { const { onTestFinished: done } = c; done(() => {}, 1000); };\nvoid later;',
      'import type { TestContext } from "vitest";\nconst later = ({ onTestFinished: done }: TestContext): void => { done(() => {}, 1000); };\nvoid later;',
      'it("x", async ({ expect }) => { await expect.poll(() => 1, { timeout: 1000 }).toBe(1); });',
      '(globalThis as any).it("x", async () => {}, 1000);',
      '(globalThis as any).vi.setConfig({ testTimeout: 1000 });',
      /* R7-V8: a modifier CALL chained on an untyped value — the defining call's callee is a call, which has no name. */
      '(globalThis as any).it.each([1])("x %s", async () => {}, 1000);',
      '(globalThis as any).it.skipIf(false)("x", async () => {}, 1000);',
      '(globalThis as any).describe.runIf(true)("x", () => {}, { timeout: 1000 });',
      '(globalThis as any).it.concurrent.for([1])("x %s", async () => {}, 1000);',
      'const g: any = globalThis;\ng["it"].each([1])("x %s", async () => {}, 1000);',
      'const opts = { timeout: 60_000 };\nopts.timeout = 1000;\nit("x", opts, async () => {});',
      'const opts = { timeout: 60_000 };\nObject.assign(opts, { timeout: 1000 });\nit("x", opts, async () => {});',
      "vi.setConfig.call(vi, { testTimeout: 1000 });",
      'Reflect.apply(vi.setConfig, vi, [{ testTimeout: 1000 }]);',
      'const k = "setConfig" as "setConfig" | "fn";\nvoid vi[k];',
      "for (const k in vi) void k;",
      'const { ["setConfig"]: s } = vi;\nvoid s;',
      "void Object.values(vi);",
      'const t: any = it;\nt("x", async () => {}, 1000);',
      '(it as any)("x", async () => {}, 1000);',
      /* R7-V2-4: an untyped value's derived function taken out under ANOTHER name, and a typed alias of an untyped read. */
      'const { it: x } = globalThis as any;\nx("n", async () => {}, 1000);',
      'const { setConfig: s } = (globalThis as any).vi;\ns({ testTimeout: 1000 });',
      'const x: typeof it = (globalThis as any).it;\nx("n", async () => {}, 1000);',
      /* The waiting functions: a low limit, and no limit at all (Vitest's own 1 s default). */
      "await vi.waitFor(() => true, { timeout: 1000 });",
      "await vi.waitFor(() => true);",
      "await vi.waitUntil(() => true, 500);",
      "await expect.poll(() => 1).toBe(1);",
      "await expect.poll(() => 1, { interval: 5 }).toBe(1);",
    ];
  const FINE_LIMITS = [
      'it("x", { timeout: 30000 }, async () => {});',
      'it("x", async () => {}, 600_000);',
      "beforeAll(async () => {}, 60_000);",
      'declare function sleep(ms: number): Promise<void>;\nit("x", async () => { await sleep(10); });',
      "const t = setTimeout(() => {}, 100);\nvoid t;",
      'declare function run(o: { timeout: number }): void;\nrun({ timeout: 100 });',
      'const LIMIT = 300_000;\nit("x", { timeout: LIMIT }, () => {});',
      'function body() { expect(1).toBe(1); }\nit("x", body);',
      'const body = async () => {};\nit("x", body);',
      'const s = `it("x", { timeout: 100 }, () => {})`;\nvoid s;',
      'it("x", async () => {}, 10 * 60_000);',
      'const OPTS = { timeout: 120_000, retry: 0 };\nit("x", OPTS, async () => {});',
      'const TABLE = [1];\nit.each(TABLE)("x %s", async () => {});',
      'const TABLE = [1];\ndescribe.each(TABLE)("x %s", () => {});',
      'it.skipIf(process.platform === "win32")("x", async () => {});',
      'it.todo("later");',
      'const name = "n";\nit(`${name} case`, async () => {});',
      "vi.setConfig({ testTimeout: 60_000, hookTimeout: 60_000 });",
      "vi.useFakeTimers();",
      'const timeout = 60_000;\nit("x", { timeout }, async () => {});',
      'it("x", { retry: 0 }, async () => {});',
      /* Typed paths the checker follows: held, and fine when the limit is. */
      'import { it as check } from "vitest";\ncheck("x", async () => {}, 60_000);',
      "const v = vi;\nv.setConfig({ testTimeout: 60_000 });",
      'it("x", async ({ onTestFinished }) => { onTestFinished(() => {}); onTestFinished(() => {}, 60_000); });',
      'afterEach(async (ctx) => { if (ctx.signal.aborted) return; });',
      'import type { TestContext } from "vitest";\nconst named = (c: TestContext): string => c.task.name;\nit("x", async (ctx) => { named(ctx); });',
      'enum Limits { Long = 60_000 }\nit("x", async () => {}, Limits.Long);',
      "await vi.waitFor(() => true, { timeout: 60_000 });",
      "await vi.waitFor(() => true, 60_000);",
      "await expect.poll(() => 1, { timeout: 60_000 }).toBe(1);",
      /* The same untyped chains, held and fine when their limit is (not reported wholesale). */
      '(globalThis as any).it.each([1])("x %s", async () => {}, 60_000);',
      '(globalThis as any).it.skipIf(false)("x", async () => {});',
      'declare const p: { waitFor(): number; poll(n: number): number };\np.waitFor();\np.poll(5);',
      'const stepUp = { poll: (_t: string, _n: number): null => null };\nstepUp.poll("low", 5999);',
      /* The same renamed and aliased shapes, held — fine when the limit is. */
      'const { it: x } = globalThis as any;\nx("n", async () => {}, 60_000);',
      'const x: typeof it = (globalThis as any).it;\nx("n", async () => {});',
    ];

  /* One program for every planted shape, built once (the unit PROGRAM_BUILD_LIMIT describes); each shape is its own case. */
  let plantedApi: { api: Api; files: ts.SourceFile[] } | undefined;
  beforeAll(() => {
    const texts = [...LOW, ...FINE_LIMITS].map((t) => `${/from "vitest"/.test(t) ? "" : VITEST_PREAMBLE}${t}\nexport {};\n`);
    const { program, files } = plantedProgram("limit-planted", texts);
    plantedApi = { api: apiOf(program), files };
  }, PROGRAM_BUILD_LIMIT);
  const plantedLow = (i: number): string[] => {
    if (plantedApi === undefined) throw new Error("the planted program was not built (beforeAll failed)");
    return lowLimits(plantedApi.api, plantedApi.files[i]!, 30_000, 30_000);
  };

  it("lists each planted shape once", () => {
    expect(new Set([...LOW, ...FINE_LIMITS]).size).toBe(LOW.length + FINE_LIMITS.length);
  });

  describe("the gate is live — it flags every shape of a low or unreadable limit", () => {
    it.each(LOW.map((t, i) => [t, i] as const))("%s", (t, i) => {
      expect(plantedLow(i), t).not.toEqual([]);
    });
  });

  describe("the gate passes a limit at or above the detector, and what is not a Vitest limit", () => {
    it.each(FINE_LIMITS.map((t, i) => [t, LOW.length + i] as const))("%s", (t, i) => {
      expect(plantedLow(i), t).toEqual([]);
    });
  });
});

/* ── a pointer into the mutation harness names a mutation that exists ──────────────────────────
   Source comments cite `review/mutation-check.mjs` by mutation id so a reader can re-run the proof
   (`--only <id>`). An id the harness does not define is a dead pointer: claims.ts cited
   `claims-c1-empty-traversal`, which `--list` never printed (the ids are claims-c1-decided-owner and
   claims-c1-both-owners). Every id-shaped token that follows a mention of the harness in authored
   source is read, and each must be one the harness defines. */
describe("every mutation id cited in source exists in review/mutation-check.mjs", () => {
  const harness = readFileSync(join(ROOT, "review", "mutation-check.mjs"), "utf8");
  const ids = new Set([...harness.matchAll(/^\s*id:\s*"([^"]+)"/gm)].map((m) => m[1]!));
  const cited: { file: string; id: string }[] = [];
  for (const f of files) {
    if (!rel(f).startsWith("src/") || !/\.(ts|tsx|css)$/.test(f) || /\.test\.tsx?$/.test(f)) continue;
    const text = readFileSync(f, "utf8").replace(/\s+/g, " ");
    for (const m of text.matchAll(/mutation-check\.mjs`?\s*\)?\s*((?:`?[a-z0-9]+(?:-[a-z0-9]+){2,}`?(?:\s*(?:,|and|\/)\s*)?)+)/g)) {
      for (const id of m[1]!.matchAll(/[a-z0-9]+(?:-[a-z0-9]+){2,}/g)) cited.push({ file: rel(f), id: id[0] });
    }
  }

  it("reads the harness's ids (an empty read is not a pass)", () => {
    expect(ids.size).toBeGreaterThan(10);
    expect(ids.has("claims-c1-decided-owner")).toBe(true);
  });

  it("finds the citations it checks", () => {
    expect(cited.length, "no source cites a mutation id — the reader is broken").toBeGreaterThan(0);
  });

  it("names no mutation the harness does not define", () => {
    expect(cited.filter((c) => !ids.has(c.id)).map((c) => `${c.file}: ${c.id}`)).toEqual([]);
  });
});
