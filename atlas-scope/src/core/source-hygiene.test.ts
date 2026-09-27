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
import { readdirSync, readFileSync, statSync } from "node:fs";
import { dirname, extname, join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import ts from "typescript";
import { describe, expect, it } from "vitest";

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

const files = walk(ROOT);
const rel = (f: string): string => relative(ROOT, f).split("\\").join("/");

describe("authored files stay text", () => {
  it("finds files to check — an empty scan is not a pass", () => {
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

  it("contains no literal NUL byte", () => {
    const offenders: string[] = [];
    for (const f of files) {
      const buf = readFileSync(f);
      let count = 0;
      for (const b of buf) if (b === 0) count++;
      if (count > 0) offenders.push(`${rel(f)} — ${count} NUL byte(s)`);
    }
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
    // Proves the detector fires. A gate whose failure path was never executed is not a gate.
    const planted = Buffer.from(`const k = \`a${String.fromCharCode(0)}b\`;`, "utf8");
    let count = 0;
    for (const b of planted) if (b === 0) count++;
    expect(count).toBe(1);
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
    const watched = files.filter((f) => {
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
 *   - It is a SCANNER, not a TypeScript parser. It strips comments and string/template literals
 *     first so prose and fixtures cannot satisfy or break it, but a regex literal containing an
 *     unescaped `/*` or a quote would confuse it. The failure mode is a FALSE POSITIVE — a real
 *     test reported as assertion-free — which is loud and diagnosable, not silent.
 *   - `it.each(...)(...)` is handled (the last call group in the chain is the definition call), but
 *     a test whose callback is a bare identifier defined in another MODULE cannot be followed, and
 *     is accepted. Helpers defined in the SAME file are followed to a fixpoint.
 *   - It says nothing about whether the assertions are GOOD. `expect(true).toBe(true)` passes this.
 *     Absence of assertion is the only thing it can see, and it is the thing that recurred.
 * ──────────────────────────────────────────────────────────────────────────────────────────────── */

/** Strip comments and the CONTENTS of string/template literals; template `${}` holes are kept. */
function stripNoise(src: string): string {
  let out = "";
  let i = 0;
  const n = src.length;
  while (i < n) {
    const c = src[i] as string;
    const d = src[i + 1];
    if (c === "/" && d === "/") {
      while (i < n && src[i] !== "\n") i++;
      continue;
    }
    if (c === "/" && d === "*") {
      i += 2;
      while (i < n && !(src[i] === "*" && src[i + 1] === "/")) i++;
      i += 2;
      continue;
    }
    if (c === '"' || c === "'" || c === "`") {
      const quote = c;
      i++;
      out += '""';
      while (i < n) {
        if (src[i] === "\\") {
          i += 2;
          continue;
        }
        if (src[i] === quote) {
          i++;
          break;
        }
        if (quote === "`" && src[i] === "$" && src[i + 1] === "{") {
          /* A template hole is CODE. `expect(...)` can live in one, and dropping it would make this
             gate lie in the direction that matters. */
          let depth = 1;
          i += 2;
          while (i < n && depth > 0) {
            if (src[i] === "{") depth++;
            else if (src[i] === "}") depth--;
            if (depth > 0) out += src[i];
            i++;
          }
          continue;
        }
        i++;
      }
      continue;
    }
    out += c;
    i++;
  }
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
function assertingHelpers(stripped: string): Set<string> {
  const names = new Set<string>();
  const decls: { name: string; body: string }[] = [];
  const re = /(?:function\s+([\w$]+)|(?:const|let|var)\s+([\w$]+)\s*=)/g;
  let m: RegExpExecArray | null;
  while ((m = re.exec(stripped)) !== null) {
    const name = m[1] ?? m[2];
    if (name === undefined) continue;
    const open = stripped.indexOf("{", m.index);
    if (open === -1) continue;
    let depth = 0;
    let end = open;
    for (let i = open; i < stripped.length; i++) {
      if (stripped[i] === "{") depth++;
      else if (stripped[i] === "}") {
        depth--;
        if (depth === 0) {
          end = i;
          break;
        }
      }
    }
    decls.push({ name, body: stripped.slice(open, end + 1) });
  }
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
    const underscored = files.map(rel).filter((f) => f.startsWith("src/") && f.split("/").some((seg) => seg.startsWith("_")));
    expect(underscored, `files under src/ the runner now skips:\n${underscored.join("\n")}`).toEqual([]);
  });

  const collected = files
    .map(rel)
    .filter((f) => f.startsWith("src/") && (f.endsWith(".test.ts") || f.endsWith(".test.tsx")));

  it("found the suite to walk", () => {
    // A walk that found nothing would pass every check below while proving nothing at all.
    expect(collected.length).toBeGreaterThan(20);
  });

  it("finds no test with zero assertions", () => {
    const offenders: string[] = [];
    for (const f of collected) {
      const stripped = stripNoise(readFileSync(resolve(ROOT, f), "utf8"));
      const helpers = assertingHelpers(stripped);
      const helperCall = helpers.size === 0 ? null : new RegExp(`\\b(?:${[...helpers].join("|")})\\b`);
      for (const t of testDefinitions(stripped)) {
        // `it("name")` with no callback is a vitest TODO, reported as todo and not as a pass.
        if (t.body === null && !/,/.test(t.raw)) continue;
        const text = t.body ?? t.raw;
        if (ASSERTION.test(text)) continue;
        if (helperCall !== null && helperCall.test(text)) continue;
        offenders.push(`${f} — ${t.name}`);
      }
    }
    expect(
      offenders,
      `tests that run, pass, and assert nothing:\n${offenders.join("\n")}`,
    ).toEqual([]);
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

  it("the gate reads code, not prose — a commented-out expect does not satisfy it", () => {
    const fake = `it("looks fine", () => {\n  // expect(x).toBe(1);\n  const s = "expect(x).toBe(1)";\n});`;
    const stripped = stripNoise(fake);
    const defs = testDefinitions(stripped);
    expect(defs).toHaveLength(1);
    expect(ASSERTION.test(defs[0]?.body ?? "")).toBe(false);
  });
});

/* ── every async act() scope goes through the shared helper (acceptance F2, the load cascade) ────
 * An async act() scope that outlives its test corrupts React's process-global act depth, and every
 * later render in the file is queued and never committed (src/test-support/act-turns.ts has the
 * mechanism). The helper stops an abandoned test at its next scope and settles every scope after
 * each test; a raw `await act(async …)` gets neither. So the rule is about the CALL, found by
 * scanning the tree rather than by naming the files that had one: outside the helper itself, no
 * source under src/ may open an async act() scope directly.
 *
 * The scan PARSES each file with the TypeScript compiler rather than stripping text. A text
 * stripper cannot tell a regex literal from division, so a quote inside one (`/'s IP address$/`)
 * opened a fake string and swallowed the next raw scope in CommandPalette.test.tsx: the gate
 * reported 3 of that file's 4 raw scopes as the whole set (verifier finding F2-V1). A raw scope is a
 * call to React's act — `act`, an alias imported for it, or `<a React import>.act` — that is
 * awaited, chained with `.then`/`.catch`/`.finally`, or handed an async function. The runtime canary
 * in src/test-setup.ts is the backstop for what syntax cannot see (a sync-looking act() whose
 * callback returns a promise). */
describe("every async act() scope in src/ goes through src/test-support/act-turns.ts", () => {
  const HELPER = "src/test-support/act-turns.ts";
  const CODE = /\.(?:[cm]?[jt]s|[jt]sx)$/;
  /* Its own walk, over every JS/TS source under src/: the text walk above collects only the
     extensions this project happens to author today, so a .mts/.cts/.jsx file would slip past it. */
  const walkCode = (dir: string, out: string[] = []): string[] => {
    for (const name of readdirSync(dir)) {
      const p = join(dir, name);
      if (statSync(p).isDirectory()) {
        if (!SKIP_DIRS.has(name)) walkCode(p, out);
      } else if (CODE.test(name) && !name.endsWith(".d.ts")) out.push(p);
    }
    return out;
  };
  const sources = walkCode(SRC).map(rel);
  const parse = (text: string, name: string): ts.SourceFile =>
    ts.createSourceFile(name, text, ts.ScriptTarget.Latest, true, /x$/.test(name) ? ts.ScriptKind.TSX : ts.ScriptKind.TS);
  const REACT_MODULE = /^(?:react(?:-dom)?(?:\/.*)?|@testing-library\/react)$/;
  const unparen = (e: ts.Expression): ts.Expression => (ts.isParenthesizedExpression(e) ? unparen(e.expression) : e);

  /** Each raw async act() scope in `text`, as `line:col <call head>`. */
  const offenders = (text: string, name = "planted.tsx"): string[] => {
    const sf = parse(text, name);
    const actNames = new Set(["act"]);
    const reactNamespaces = new Set(["React"]);
    for (const st of sf.statements) {
      if (!ts.isImportDeclaration(st) || !ts.isStringLiteral(st.moduleSpecifier) || st.importClause === undefined) continue;
      const fromReact = REACT_MODULE.test(st.moduleSpecifier.text);
      const clause = st.importClause;
      if (fromReact && clause.name !== undefined) reactNamespaces.add(clause.name.text);
      const bindings = clause.namedBindings;
      if (bindings === undefined) continue;
      if (ts.isNamespaceImport(bindings)) {
        if (fromReact) reactNamespaces.add(bindings.name.text);
      } else {
        for (const el of bindings.elements) if ((el.propertyName ?? el.name).text === "act") actNames.add(el.name.text);
      }
    }
    const isAct = (callee: ts.Expression): boolean => {
      const e = unparen(callee);
      if (ts.isIdentifier(e)) return actNames.has(e.text);
      if (ts.isPropertyAccessExpression(e) && e.name.text === "act") {
        const obj = unparen(e.expression);
        return ts.isIdentifier(obj) && reactNamespaces.has(obj.text);
      }
      return false;
    };
    const isAsyncFn = (a: ts.Expression): boolean =>
      (ts.isArrowFunction(a) || ts.isFunctionExpression(a)) && (ts.getCombinedModifierFlags(a) & ts.ModifierFlags.Async) !== 0;
    const found: string[] = [];
    const visit = (n: ts.Node): void => {
      if (ts.isCallExpression(n) && isAct(n.expression)) {
        let up: ts.Node = n.parent;
        while (ts.isParenthesizedExpression(up)) up = up.parent;
        const awaited = ts.isAwaitExpression(up);
        const chained = ts.isPropertyAccessExpression(up) && /^(?:then|catch|finally)$/.test(up.name.text);
        if (awaited || chained || n.arguments.some((a) => isAsyncFn(unparen(a)))) {
          const { line, character } = sf.getLineAndCharacterOfPosition(n.getStart(sf));
          found.push(`${line + 1}:${character + 1} ${n.getText(sf).replace(/\s+/g, " ").slice(0, 32)}`);
        }
      }
      ts.forEachChild(n, visit);
    };
    visit(sf);
    return found;
  };

  /** The module specifiers `text` imports from. */
  const importsOf = (text: string, name: string): string[] =>
    parse(text, name)
      .statements.filter(ts.isImportDeclaration)
      .map((st) => (ts.isStringLiteral(st.moduleSpecifier) ? st.moduleSpecifier.text : ""));
  /** Whether `text` calls one of the helper's scope-opening exports. */
  const callsHelper = (text: string, name: string): boolean => {
    let yes = false;
    const visit = (n: ts.Node): void => {
      if (ts.isCallExpression(n) && ts.isIdentifier(n.expression) && /^(?:actAsync|flushTurns)$/.test(n.expression.text)) yes = true;
      if (!yes) ts.forEachChild(n, visit);
    };
    visit(parse(text, name));
    return yes;
  };

  it("walked the source tree and found the helper in it", () => {
    expect(sources.length).toBeGreaterThan(50);
    expect(sources).toContain(HELPER);
  });

  it("no file outside the helper opens an async act() scope directly", () => {
    const found = sources
      .filter((f) => f !== HELPER)
      .flatMap((f) => offenders(readFileSync(resolve(ROOT, f), "utf8"), f).map((opened) => `${f}:${opened}`));
    expect(found, `raw async act() scopes; use actAsync/flushTurns from ${HELPER}:\n${found.join("\n")}`).toEqual([]);
  });

  it("the files that drive React asynchronously do use the helper (the class is not empty)", () => {
    const users = sources.filter((f) => f !== HELPER && callsHelper(readFileSync(resolve(ROOT, f), "utf8"), f));
    expect(users.length, "no test opens an async act() scope through the helper: the scan is reading nothing").toBeGreaterThan(10);
    /* Every such file imports it, whatever the relative prefix. */
    const fromHelper = (spec: string): boolean => /^(?:\.{1,2}\/)+(?:[\w-]+\/)*test-support\/act-turns(?:\.ts)?$/.test(spec);
    expect(users.filter((f) => !importsOf(readFileSync(resolve(ROOT, f), "utf8"), f).some(fromHelper))).toEqual([]);
  });

  it("the gate is live — it flags every raw shape and passes the helper's", () => {
    const raw = [
      "await act(async () => { await flush(); });",
      "await act(() => store.set(1));",
      "await React.act(async () => {});",
      "void act(async () => {});",
      "const p = act(async () => {});",
      "const p = act(async function () {});",
      "act(() => pending).then(done);",
      "await (act)(() => store.set(1));",
      /* F2-V1: a quote inside a regex literal before the call. The text stripper this replaced read
         it as the start of a string and swallowed the scope. */
      "const re = /^matched this [\\w -]+'s \\w/;\nawait act(async () => {});",
      "const re = /'s IP address$/;\nconst flush = (): Promise<void> => act(async () => {});",
      'import { act as flushReact } from "react";\nawait flushReact(async () => {});',
      'import * as R from "react";\nawait R.act(async () => {});',
      'import TL from "@testing-library/react";\nawait TL.act(async () => {});',
    ];
    /* `export {}` makes each planted text a module, as every real file is: in a script, top-level
       `await (act)(…)` parses as a call of an identifier named `await`. */
    for (const r of raw) expect(offenders(`${r}
export {};`), r).toHaveLength(1);
    const fine = [
      "await actAsync(async () => { await flush(); });",
      "act(() => root.render(ui));",
      "await flushTurns(10, 3);",
      "// await act(async () => {}) in a comment",
      'const s = "await act(async () => {})";',
      "const re = /await act\\(async/;",
      "const t = `await act(async () => {}) ${x}`;",
      /* A journey's own act(), not React's: a member call on something that is not a React import. */
      "await j.act(page, 0).catch(() => null);",
    ];
    for (const f of fine) expect(offenders(`${f}
export {};`), f).toEqual([]);
  });
});

/* ── no test carries a time limit below the configured hang detector (acceptance F2, load) ─────
 * vitest.config.ts sets `testTimeout`/`hookTimeout` as a HANG detector and states the rule a unit
 * test lives by: it asserts no wall-clock time. A per-call limit BELOW that detector is a
 * wall-clock assertion under another name — the test goes red when the host is busy, not when the
 * code regressed. Three files carried one (`{ timeout: 15000 }` / `{ timeout: 20000 }` on whole-App
 * mounts in reaim-tab-and-restore, selection-origin and surfaces), and on both loaded F2 runs they
 * were the only red in the F2-owned files. Limits ABOVE the detector stay each owner's to justify
 * (the config says so); limits below it are not a choice this suite offers. The set is every test
 * file the runner collects, found by parsing, and the detector values are read from the config
 * itself, failing closed if they move out of reach. */
describe("no test or hook sets a time limit below the configured hang detector", () => {
  const configText = readFileSync(resolve(ROOT, "vitest.config.ts"), "utf8");
  const configured = (key: string): number | null => {
    let found: number | null = null;
    const visit = (n: ts.Node): void => {
      if (ts.isPropertyAssignment(n) && ts.isIdentifier(n.name) && n.name.text === key && ts.isNumericLiteral(n.initializer)) {
        found = Number(n.initializer.text.replace(/_/g, ""));
      }
      ts.forEachChild(n, visit);
    };
    visit(ts.createSourceFile("vitest.config.ts", configText, ts.ScriptTarget.Latest, true, ts.ScriptKind.TS));
    return found;
  };
  const TEST_LIMIT = configured("testTimeout");
  const HOOK_LIMIT = configured("hookTimeout");
  const TESTS = new Set(["it", "test", "describe", "suite", "bench"]);
  const HOOKS = new Set(["beforeEach", "afterEach", "beforeAll", "afterAll", "aroundEach", "aroundAll"]);

  /** The runner function a call ultimately names: `it`, `it.each(t)`, `test.skip.each(t)` → `it`/`test`. */
  const rootName = (callee: ts.Expression): string | null => {
    let e: ts.Expression = callee;
    for (;;) {
      if (ts.isPropertyAccessExpression(e)) e = e.expression;
      else if (ts.isCallExpression(e)) e = e.expression;
      else if (ts.isParenthesizedExpression(e)) e = e.expression;
      else break;
    }
    return ts.isIdentifier(e) ? e.text : null;
  };
  /** Each limit below the detector in `text`, as `line: <runner> <value>`. */
  const lowLimits = (text: string, name: string, testLimit: number, hookLimit: number): string[] => {
    const sf = ts.createSourceFile(name, text, ts.ScriptTarget.Latest, true, /x$/.test(name) ? ts.ScriptKind.TSX : ts.ScriptKind.TS);
    /* A limit named by a `const NAME = <number>` in the same file is read through the name. */
    const consts = new Map<string, number>();
    const collect = (n: ts.Node): void => {
      if (ts.isVariableDeclarationList(n) && (n.flags & ts.NodeFlags.Const) !== 0) {
        for (const d of n.declarations) {
          if (ts.isIdentifier(d.name) && d.initializer !== undefined && ts.isNumericLiteral(d.initializer)) consts.set(d.name.text, Number(d.initializer.text.replace(/_/g, "")));
        }
      }
      ts.forEachChild(n, collect);
    };
    collect(sf);
    const valueOf = (v: ts.Expression): number | null =>
      ts.isNumericLiteral(v) ? Number(v.text.replace(/_/g, "")) : ts.isIdentifier(v) ? (consts.get(v.text) ?? null) : null;
    const out: string[] = [];
    const visit = (n: ts.Node): void => {
      if (ts.isCallExpression(n)) {
        const runner = rootName(n.expression);
        const limit = runner === null ? null : TESTS.has(runner) ? testLimit : HOOKS.has(runner) ? hookLimit : null;
        if (limit !== null) {
          const values: ts.Expression[] = [];
          for (const a of n.arguments) {
            /* A positional limit is a number or a name for one; a callback passed by name is skipped below. */
            if (ts.isNumericLiteral(a) || ts.isIdentifier(a)) values.push(a);
            else if (ts.isObjectLiteralExpression(a)) {
              for (const p of a.properties) {
                if (ts.isPropertyAssignment(p) && (ts.isIdentifier(p.name) || ts.isStringLiteral(p.name)) && p.name.text === "timeout") values.push(p.initializer);
              }
            }
          }
          for (const v of values) {
            const line = sf.getLineAndCharacterOfPosition(v.getStart(sf)).line + 1;
            const value = valueOf(v);
            /* A `timeout:` this cannot resolve is reported, not assumed fine. A positional identifier that
               names no number constant is a callback passed by name, not a limit. */
            if (value === null) {
              if (v.parent !== n) out.push(`${line}: ${runner} timeout is not a number it can read (${v.getText(sf)})`);
            } else if (value < limit) out.push(`${line}: ${runner} ${v.getText(sf)} < ${limit}`);
          }
        }
      }
      ts.forEachChild(n, visit);
    };
    visit(sf);
    return out;
  };

  it("read both hang-detector limits from vitest.config.ts", () => {
    expect(TEST_LIMIT, "vitest.config.ts no longer sets testTimeout as a numeric literal").not.toBeNull();
    expect(HOOK_LIMIT, "vitest.config.ts no longer sets hookTimeout as a numeric literal").not.toBeNull();
  });

  it("every collected test file keeps to them", () => {
    const tests = files.map(rel).filter((f) => /^src\/.*\.test\.tsx?$/.test(f) && !/\/_/.test(f));
    expect(tests.length, "the walk found the suite").toBeGreaterThan(100);
    const low = tests.flatMap((f) => lowLimits(readFileSync(resolve(ROOT, f), "utf8"), f, TEST_LIMIT!, HOOK_LIMIT!).map((l) => `${f}:${l}`));
    expect(low, `per-call limits below the configured hang detector (a wall-clock assertion under load):\n${low.join("\n")}`).toEqual([]);
  });

  it("the gate is live — it flags every shape of a low limit and passes the rest", () => {
    const low = [
      'it("x", { timeout: 15000 }, async () => {});',
      'it("x", async () => {}, 15_000);',
      'test.each([1])("x %s", async () => {}, { timeout: 100 });',
      'it.skip("x", { "timeout": 20000 }, () => {});',
      'describe("x", { timeout: 1000 }, () => {});',
      "beforeEach(async () => {}, 5000);",
      'it("x", { timeout: LIMIT }, () => {});',
      'const LIMIT = 10_000;\nit("x", { timeout: LIMIT }, () => {});',
      'const LIMIT = 10_000;\nit("x", async () => {}, LIMIT);',
    ];
    for (const l of low) expect(lowLimits(l, "planted.ts", 30_000, 30_000), l).toHaveLength(1);
    const fine = [
      'it("x", { timeout: 30000 }, async () => {});',
      'it("x", async () => {}, 600_000);',
      "beforeAll(async () => {}, 60_000);",
      'it("x", async () => { await sleep(10); });',
      'const t = setTimeout(() => {}, 100);',
      'run({ timeout: 100 });',
      'const LIMIT = 300_000;\nit("x", { timeout: LIMIT }, () => {});',
      'it("x", body);',
      'const s = `it("x", { timeout: 100 }, () => {})`;',
    ];
    for (const f of fine) expect(lowLimits(f, "planted.ts", 30_000, 30_000), f).toEqual([]);
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
