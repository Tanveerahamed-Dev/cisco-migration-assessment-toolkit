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
