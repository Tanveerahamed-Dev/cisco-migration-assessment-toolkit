/**
 * scripts-typecheck.test.ts — the build scripts are type-checked, and this is what runs it.
 *
 * WHY. `tsconfig.json` includes "tools" and "e2e", which reads as coverage of the seven .mjs
 * build/capture/measurement scripts. It is not: `allowJs` is off, so `npx tsc -p tsconfig.json
 * --noEmit --listFiles` lists 77 files and zero of them are .mjs, and `e2e/` does not exist (a
 * `playwright test` script is declared with no config and no directory). A type error in
 * `tools/compile-snapshot.mjs` — the only bridge between the assessment snapshot and every number
 * the UI renders — was invisible to the command F1 cites as its evidence.
 *
 * The scope, and the honest naming of what is still outside it, is in `tsconfig.scripts.json`.
 *
 * WHY IT RUNS HERE rather than as an npm script: a gate nobody invokes is not a gate, and
 * `npx vitest run` is the command this project's acceptance actually names. The program is built
 * in-process through the TypeScript API — no subprocess, ~1 s — and the config is READ from the
 * file rather than restated, so the two cannot drift.
 */
import { execFileSync } from "node:child_process";
import { existsSync, mkdtempSync, readdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, relative, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import ts from "typescript";
import { beforeAll, describe, expect, it } from "vitest";

const PKG = resolve(dirname(fileURLToPath(import.meta.url)), "..", "..");
const CONFIG = resolve(PKG, "tsconfig.scripts.json");

/* ── one parse per file per project, shared by every program this file builds ─────────────────────
 * Each test here builds a whole TypeScript program, and most of that cost is parsing and binding the
 * same declaration files again (the lib files; for the config project, all of Vite's and Vitest's
 * types). On the loaded F2 re-runs (12 busy loops on a 14-core host already carrying other agents)
 * three of these tests crossed the 30 s hang detector while solo they take about 1 s. The unit of
 * work is not raised; the repeated setup is shared, as vitest.config.ts prescribes. A SourceFile is
 * reused only by programs built with the SAME compiler options (it is bound once, under the options
 * of the program that first bound it). A PLANTED text is never cached, and never served to a
 * program that did not plant it: every liveness test below still sees its own in-memory error. */
const sourceFiles = new Map<string, Map<string, ts.SourceFile>>();

/* The one limit ABOVE the configured detector in this file, and why (the same unit, and the same
   reason, as source-hygiene.test.ts's PROGRAM_BUILD_LIMIT): the unit of work is one whole-program parse,
   bind and check of a project (the scripts, or the runner/bundler configs with all of Vite's and
   Vitest's types). It cannot be split — every file's types depend on the rest — and it asserts nothing
   about time. Every such build runs in a beforeAll under this limit; everything that ASSERTS runs in a
   test, inside the detector. MEASURED (independent verifier R7-V2-5, 12 busy loops): the config
   project's build inside a test body crossed the 30 s detector. The last describe below checks the rule
   over this file's own source. */
const PROGRAM_BUILD_LIMIT = 300_000;

function sharedHost(options: ts.CompilerOptions, planted: ReadonlyMap<string, string> = new Map()): ts.CompilerHost {
  const host = ts.createCompilerHost(options, true);
  const cache = sourceFiles.get(JSON.stringify(options)) ?? new Map<string, ts.SourceFile>();
  sourceFiles.set(JSON.stringify(options), cache);
  const readFile = host.readFile.bind(host);
  const fileExists = host.fileExists.bind(host);
  const getSourceFile = host.getSourceFile.bind(host);
  host.readFile = (f) => planted.get(resolve(f)) ?? readFile(f);
  host.fileExists = (f) => planted.has(resolve(f)) || fileExists(f);
  host.getSourceFile = (fileName, languageVersionOrOptions, onError, shouldCreate) => {
    const text = planted.get(resolve(fileName));
    if (text !== undefined) return ts.createSourceFile(fileName, text, languageVersionOrOptions, true);
    const key = `${resolve(fileName)}\0${JSON.stringify(languageVersionOrOptions)}`;
    const hit = cache.get(key);
    if (hit !== undefined) return hit;
    const made = getSourceFile(fileName, languageVersionOrOptions, onError, shouldCreate);
    if (made !== undefined) cache.set(key, made);
    return made;
  };
  return host;
}

/** The planted .mjs the checkJs liveness case reads (never written to disk). */
const LIVENESS_FILE = resolve(PKG, "tools", "__typecheck_liveness.mjs");
const LIVENESS_TEXT = "const n = 1;\nn.toFixed(2, 3, 4);\nexport default n;\n";

function check(): { files: string[]; diagnostics: string[]; program: ts.Program; options: ts.CompilerOptions } {
  const raw = ts.readConfigFile(CONFIG, (p) => readFileSync(p, "utf8"));
  expect(raw.error, `tsconfig.scripts.json could not be read`).toBeUndefined();
  const parsed = ts.parseJsonConfigFileContent(raw.config, ts.sys, PKG, undefined, CONFIG);
  expect(
    parsed.errors.filter((d) => d.category === ts.DiagnosticCategory.Error).map((d) => d.messageText),
  ).toEqual([]);

  const program = ts.createProgram(parsed.fileNames, parsed.options, sharedHost(parsed.options));
  const diagnostics = [...program.getSemanticDiagnostics(), ...program.getSyntacticDiagnostics()]
    .map((d) => {
      const where =
        d.file === undefined || d.start === undefined
          ? ""
          : `${relative(PKG, d.file.fileName).split("\\").join("/")}:${
              d.file.getLineAndCharacterOfPosition(d.start).line + 1
            } `;
      return `${where}${ts.flattenDiagnosticMessageText(d.messageText, " ")}`;
    })
    .sort();

  return {
    files: parsed.fileNames.map((f) => relative(PKG, f).split("\\").join("/")),
    diagnostics,
    program,
    options: parsed.options,
  };
}

describe("the build scripts are inside a type-checking gate", () => {
  /* The whole-program builds, once each, in the bounded hook (see PROGRAM_BUILD_LIMIT). */
  let built: { result: ReturnType<typeof check>; liveness: string[]; strict: ts.Program } | undefined;
  beforeAll(() => {
    const result = check();
    /* A checkJs typo would make the gate pass over any file at all: a real error planted in memory. */
    const raw = ts.readConfigFile(CONFIG, (p) => readFileSync(p, "utf8"));
    const parsed = ts.parseJsonConfigFileContent(raw.config, ts.sys, PKG, undefined, CONFIG);
    const program = ts.createProgram([LIVENESS_FILE], parsed.options, sharedHost(parsed.options, new Map([[LIVENESS_FILE, LIVENESS_TEXT]])));
    const liveness = program.getSemanticDiagnostics().map((d) => ts.flattenDiagnosticMessageText(d.messageText, " "));
    /* The forced-on program IS the one the gate already built whenever the config's effective setting is
       on (strict, and noImplicitAny not switched off), so it is reused rather than built a second time.
       Only a config that switches the flag off gets a program of its own, and it is red below anyway. */
    const effective = result.options.noImplicitAny ?? result.options.strict === true;
    const strict = effective ? result.program : ts.createProgram(parsed.fileNames, { ...parsed.options, noImplicitAny: true });
    built = { result, liveness, strict };
  }, PROGRAM_BUILD_LIMIT);
  const now = (): NonNullable<typeof built> => {
    if (built === undefined) throw new Error("the scripts' program was not built (beforeAll failed)");
    return built;
  };

  it("checks the scripts the main config only appears to cover", () => {
    /* The denominator, pinned. An empty file list would make the assertion below vacuous, which is
       exactly the shape of the defect this file answers. */
    const { result } = now();
    expect(result.files).toContain("tools/compile-snapshot.mjs");
    expect(result.files.every((f) => f.endsWith(".mjs"))).toBe(true);
    expect(result.files.length).toBeGreaterThan(0);
  });

  it("reports no type error in them", () => {
    const { result } = now();
    expect(result.diagnostics, `type errors in the build scripts:\n${result.diagnostics.join("\n")}`).toEqual(
      [],
    );
  });

  it("is checking JavaScript, not silently skipping it", () => {
    /* A `checkJs: false` typo would make the gate above pass over any file at all. Plant a real
       error in memory and confirm the same settings report it. */
    const found = now().liveness;
    expect(found.join(" "), "the same settings must reject a real error in a .mjs file").toMatch(
      /Expected 0-1 arguments|Expected 1 arguments/,
    );
    // ...and the planted file was never written to disk.
    expect(existsSync(LIVENESS_FILE)).toBe(false);
  });

  it("is fully strict: noImplicitAny is ON, and the scripts are clean under it", () => {
    /* HISTORY. Until 2026-09-22 this project ran `strict` minus `noImplicitAny`, and this test
       pinned the measured residual (18 diagnostics, 12 TS7006 + 6 TS7053, every one in
       `tools/compile-snapshot.mjs`) with a note that annotating it to zero was the signal to flip
       the flag. It has been annotated (JSDoc, output byte-identical) and the flag is on.
       Two assertions, because either alone could lie: the CONFIG must say so (so `tsc -p` and the
       gate above check it), and a program built with the flag FORCED on must also be clean (so a
       future `"noImplicitAny": false` cannot hide a regression behind a green config read). */
    const raw = ts.readConfigFile(CONFIG, (p) => readFileSync(p, "utf8"));
    const parsed = ts.parseJsonConfigFileContent(raw.config, ts.sys, PKG, undefined, CONFIG);
    expect(parsed.options.strict).toBe(true);
    expect(parsed.options.noUncheckedIndexedAccess).toBe(true);
    expect(parsed.options.noImplicitAny, "tsconfig.scripts.json must not relax noImplicitAny").not.toBe(false);

    /* The forced-on program was built in the beforeAll (the gate's own, reused, when the config's
       effective setting is on). */
    const strictProgram = now().strict;
    expect(strictProgram.getCompilerOptions().noImplicitAny ?? strictProgram.getCompilerOptions().strict, "the program checked has noImplicitAny on").toBe(true);
    const extra = strictProgram.getSemanticDiagnostics().map((d) => {
      const file = d.file === undefined ? "" : relative(PKG, d.file.fileName).split("\\").join("/");
      const line = d.file === undefined || d.start === undefined ? 0 : d.file.getLineAndCharacterOfPosition(d.start).line + 1;
      return `${file}:${line} TS${d.code} ${ts.flattenDiagnosticMessageText(d.messageText, " ")}`;
    });
    expect(extra, "implicit-any (or other) diagnostics under noImplicitAny").toEqual([]);
  });

  it("names what it does not cover, rather than implying it does", () => {
    // `e2e` is declared in tsconfig.json's include and in an npm script, and does not exist.
    // Asserted so the next person reads it here instead of rediscovering it.
    expect(existsSync(resolve(PKG, "e2e"))).toBe(false);
    const scripts = readFileSync(CONFIG, "utf8");
    expect(scripts).toContain("review/*.mjs");
  });
});

/* ── the runner and bundler configs, and the class they belonged to (acceptance F1 scope) ──────────
 *
 * WHAT WAS WRONG (independent refuter, wave 3). `vitest.config.ts` set `minWorkers: 1`, which Vitest 4
 * removed, so it was silently ignored; `vite.config.ts` ended in `as any`. Neither was in ANY
 * type-checked project, so nothing could have said so. Adding the two files to a project fixes the
 * instance; the class is "an authored TypeScript/JavaScript file no project reads", and that is what
 * is checked here: every such file Git does not ignore must be in the file list of some
 * `tsconfig*.json` at the package root — derived from the tree and the projects, not from a list.
 *
 * `tsconfig.json` (the app, ~200 files, ~25 s) is type-checked by `npm run build` and the F1
 * command rather than in-process here; its FILE LIST is still part of the coverage check below. The
 * two small projects are type-checked here. */

/** Every root `tsconfig*.json`, parsed. */
function projects(): { name: string; parsed: ts.ParsedCommandLine }[] {
  return readdirSync(PKG)
    .filter((n) => /^tsconfig.*\.json$/.test(n))
    .sort()
    .map((name) => {
      const file = resolve(PKG, name);
      const raw = ts.readConfigFile(file, (p) => readFileSync(p, "utf8"));
      expect(raw.error, `${name} could not be read`).toBeUndefined();
      return { name, parsed: ts.parseJsonConfigFileContent(raw.config, ts.sys, PKG, undefined, file) };
    });
}

const posixRel = (f: string): string => relative(PKG, f).split("\\").join("/");

/** Authored TS/JS in the tree: tracked, or untracked and not ignored. */
function authoredScripts(): string[] {
  return execFileSync("git", ["ls-files", "--cached", "--others", "--exclude-standard", "-z"], { cwd: PKG, encoding: "utf8" })
    .split("\0")
    .filter((f) => /\.(ts|tsx|mts|cts|js|mjs|cjs)$/.test(f) && existsSync(resolve(PKG, f)))
    .sort();
}

/* The one declared exclusion, as the CLASS it is (every harness directly under review/), with the
   reason stated in tsconfig.scripts.json's header: code inside page.evaluate() runs in the browser.
   Measured 2026-09-23 under this repo's strict settings with checkJs: 919 diagnostics across 14 of
   the 17 harnesses — annotation work in files another lane owns, not a settings change. */
const DECLARED_OUTSIDE = /^review\/[^/]+\.mjs$/;

function diagnosticsOf(program: ts.Program): string[] {
  return [...program.getSyntacticDiagnostics(), ...program.getSemanticDiagnostics()].map((d) => {
    const where =
      d.file === undefined || d.start === undefined ? "" : `${posixRel(d.file.fileName)}:${d.file.getLineAndCharacterOfPosition(d.start).line + 1} `;
    return `${where}TS${d.code} ${ts.flattenDiagnosticMessageText(d.messageText, " ")}`;
  });
}

describe("every authored script is inside a type-checked project", () => {
  it("each root project is readable and non-empty, and the config project exists", () => {
    const ps = projects();
    expect(ps.map((p) => p.name)).toEqual(expect.arrayContaining(["tsconfig.json", "tsconfig.scripts.json", "tsconfig.config.json"]));
    for (const p of ps) {
      expect(p.parsed.errors.filter((d) => d.category === ts.DiagnosticCategory.Error).map((d) => d.messageText), p.name).toEqual([]);
      expect(p.parsed.fileNames.length, `${p.name} reads no file`).toBeGreaterThan(0);
    }
  });

  it("no authored .ts/.tsx/.mjs/.js file is outside every project, except the declared review/ harnesses", () => {
    const covered = new Set(projects().flatMap((p) => p.parsed.fileNames.map(posixRel)));
    const files = authoredScripts();
    expect(files, "the tree walk found the configs").toEqual(expect.arrayContaining(["vite.config.ts", "vitest.config.ts", "tools/compile-snapshot.mjs"]));
    const outside = files.filter((f) => !covered.has(f));
    const undeclared = outside.filter((f) => !DECLARED_OUTSIDE.test(f));
    expect(undeclared, `authored scripts no tsconfig*.json reads:\n${undeclared.join("\n")}`).toEqual([]);
    // The exclusion is exercised, not hypothetical — and it is stated where the configs live.
    expect(outside.length, "the declared review/ exclusion").toBeGreaterThan(0);
    expect(readFileSync(CONFIG, "utf8")).toContain("review/*.mjs");
  });

  /* The config project's two whole-program builds (clean, and with the defect planted back in memory),
     once each, in the bounded hook (see PROGRAM_BUILD_LIMIT) — the unit that crossed the detector. */
  let configBuilt: { p: { name: string; parsed: ts.ParsedCommandLine }; clean: string[]; planted: string } | undefined;
  beforeAll(() => {
    const p = projects().find((x) => x.name === "tsconfig.config.json")!;
    const clean = diagnosticsOf(ts.createProgram(p.parsed.fileNames, p.parsed.options, sharedHost(p.parsed.options)));
    const vitestCfg = resolve(PKG, "vitest.config.ts");
    const viteCfg = resolve(PKG, "vite.config.ts");
    const vitestText = readFileSync(vitestCfg, "utf8");
    const planted = new Map<string, string>([
      [vitestCfg, vitestText.replace("maxWorkers: WORKERS,", "maxWorkers: WORKERS,\n      minWorkers: 1,")],
      [viteCfg, `${readFileSync(viteCfg, "utf8")}\nexport const planted: number = "not a number";\n`],
    ]);
    const found = diagnosticsOf(ts.createProgram(p.parsed.fileNames, p.parsed.options, sharedHost(p.parsed.options, planted))).join("\n");
    configBuilt = { p, clean, planted: found };
  }, PROGRAM_BUILD_LIMIT);
  const config = (): NonNullable<typeof configBuilt> => {
    if (configBuilt === undefined) throw new Error("the config project's program was not built (beforeAll failed)");
    return configBuilt;
  };

  it("tsconfig.config.json reads both configs and is clean under strict", () => {
    const { p, clean: found } = config();
    expect(p.parsed.fileNames.map(posixRel).sort()).toEqual(["vite.config.ts", "vitest.config.ts"]);
    expect(p.parsed.options.strict).toBe(true);
    expect(p.parsed.options.noUncheckedIndexedAccess).toBe(true);
    expect(found, `type errors in the runner/bundler configs:\n${found.join("\n")}`).toEqual([]);
  });

  it("is live: the dead option and a type error, planted back in memory, are both reported", () => {
    /* The exact defect, restored in memory only, plus a plain type error in the build config: a gate
       whose failure path never ran is not a gate. The files on disk are never written. */
    /* The planted text must still find its anchor, or the planted program proves nothing. */
    expect(readFileSync(resolve(PKG, "vitest.config.ts"), "utf8")).toMatch(/maxWorkers: WORKERS,/);
    const found = config().planted;
    expect(found).toMatch(/vitest\.config\.ts:\d+ TS2769 .*minWorkers/);
    expect(found).toMatch(/vite\.config\.ts:\d+ TS2322/);
  });
});

/* ── the runtime assertion guard (acceptance F2) ─────────────────────────────────────────────────
 * src/test-support/test-setup.ts fails any test that makes zero assertions WHEN IT RUNS. These tests prove it is
 * installed by the real config, that it really fails such a test and names it, that it leaves an
 * asserting test alone, and that its one opt-out is explicit and justified wherever it is used. */
describe("every test makes at least one assertion when it runs", () => {
  it("the guard ran in this very worker (the real config's setupFiles installed it)", () => {
    expect((globalThis as Record<symbol, unknown>)[Symbol.for("atlas-scope.assertion-guard.installed")]).toBe(true);
    expect(readFileSync(resolve(PKG, "vitest.config.ts"), "utf8")).toMatch(/setupFiles:\s*\[fileURLToPath\(new URL\("\.\/src\/test-support\/test-setup\.ts"/);
  });

  it("a planted zero-assertion test FAILS under the real config and is named; an asserting one passes", () => {
    const dir = mkdtempSync(join(tmpdir(), "atlas-guard-"));
    try {
      const configUrl = pathToFileURL(resolve(PKG, "vitest.config.ts")).href;
      writeFileSync(
        join(dir, "planted.vitest.config.mts"),
        [
          `import base from ${JSON.stringify(configUrl)};`,
          "const b = base as { test?: Record<string, unknown> } & Record<string, unknown>;",
          // Everything of the real config (setupFiles included) except where and what to collect.
          `export default { ...b, root: ${JSON.stringify(dir)}, test: { ...b.test, environment: "node", include: ["planted.test.ts"], exclude: [] } };`,
        ].join("\n"),
      );
      const optOut = ["expect", "assertions(0)"].join(".");
      writeFileSync(
        join(dir, "planted.test.ts"),
        [
          'it("PLANTED zero-assertion loop over an empty list", () => { const xs: number[] = []; for (const x of xs) expect(x).toBe(1); });',
          'it("PLANTED asserting test", () => { expect(1).toBe(1); });',
          `it("PLANTED explicit opt-out", () => { ${optOut}; });`,
        ].join("\n"),
      );
      const out = join(dir, "result.json");
      let exit = 0;
      try {
        execFileSync(
          process.execPath,
          [resolve(PKG, "node_modules", "vitest", "vitest.mjs"), "run", "--config", join(dir, "planted.vitest.config.mts"), "--reporter=json", `--outputFile=${out}`],
          { cwd: dir, encoding: "utf8", stdio: "pipe", env: { ...process.env, VITE_CONFIG_NATIVE_IGNORE_WARNING: "true" } },
        );
      } catch (e) {
        exit = (e as { status?: number }).status ?? -1;
      }
      expect(exit, "the child run must fail: it contains a zero-assertion test").toBe(1);
      const report = JSON.parse(readFileSync(out, "utf8")) as {
        testResults: { assertionResults: { title: string; status: string; failureMessages: string[] }[] }[];
      };
      const byTitle = new Map(report.testResults.flatMap((f) => f.assertionResults).map((a) => [a.title, a]));
      expect([...byTitle.keys()].sort()).toEqual([
        "PLANTED asserting test",
        "PLANTED explicit opt-out",
        "PLANTED zero-assertion loop over an empty list",
      ]);
      const zero = byTitle.get("PLANTED zero-assertion loop over an empty list")!;
      expect(zero.status).toBe("failed");
      expect(zero.failureMessages.join("\n")).toMatch(
        /\[assertion guard\] .*planted\.test\.ts > PLANTED zero-assertion loop over an empty list made ZERO assertions/,
      );
      expect(byTitle.get("PLANTED asserting test")!.status).toBe("passed");
      expect(byTitle.get("PLANTED explicit opt-out")!.status).toBe("passed");
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  }, 60_000);

  it("the one opt-out (Vitest's own zero-count assertions call) is justified on the line above wherever a test uses it", () => {
    const walk = (d: string): string[] =>
      readdirSync(d, { withFileTypes: true }).flatMap((e) => {
        if (e.name === "node_modules") return [];
        const p = join(d, e.name);
        return e.isDirectory() ? walk(p) : /\.test\.tsx?$/.test(e.name) ? [p] : [];
      });
    const tests = walk(resolve(PKG, "src"));
    expect(tests.length, "the walk found the suite").toBeGreaterThan(50);
    const needle = new RegExp(["expect", "assertions\\(\\s*0\\s*\\)"].join("\\."));
    const unjustified: string[] = [];
    for (const f of tests) {
      const lines = readFileSync(f, "utf8").split("\n");
      lines.forEach((line, i) => {
        if (/^\s*(\/\/|\*|\/\*)/.test(line) || !needle.test(line)) return;
        if (!/assertion-guard:\s*\S/.test(lines[i - 1] ?? "")) unjustified.push(`${posixRel(f)}:${i + 1}`);
      });
    }
    expect(unjustified, "an opt-out from the assertion guard with no `assertion-guard: <reason>` comment above it").toEqual([]);
  });
});

/* ── act-scope containment and the act-scope canary (acceptance F2, the load cascade) ────────────
 * One 37 s load timeout in self-removing-focus.test.tsx was followed by 277 failures: Vitest does
 * not stop a timed-out body, the abandoned body's async act() scope interleaved with the next
 * case's, and React's act depth stuck at 1 so nothing committed for the rest of the file. The fix
 * is src/test-support/act-turns.ts (checkpoints on the test's own signal; every scope settled after
 * each test) plus the canary in src/test-support/test-setup.ts. These tests run a PLANTED file through a child
 * Vitest with the real config, three ways:
 *   - contained: each planted abandonment through the helper costs exactly ONE red. There are two,
 *     one per checkpoint, so each checkpoint is pinned on its own (verifier finding F2-V3: with one
 *     abandonment, either checkpoint alone stopped it and removing the other survived). ABANDONED is
 *     parked INSIDE a scope and does plain work the moment that scope closes, which only the
 *     checkpoint AFTER a scope stops. ABANDONED IN A TIMER is parked in a bare timer and then opens a
 *     scope, which only the checkpoint BEFORE a scope stops. Case 9 asserts neither ever ran on;
 *   - raw: the same planted file with raw act() cascades, and the canary names the leak — so the
 *     planted scenario is live and the containment is what makes the difference;
 *   - canary: an un-awaited act() scope in an otherwise passing test is failed and named, while an
 *     act() whose callback throws (a residue the canary must clear, not report) is left alone.
 * ORDERED, not timed: the abandoned case waits on a gate the next case opens, so in the raw variant
 * the out-of-order close happens by construction. The 5 s fallback exists only so the contained
 * variant (where the settle keeps the next case from starting first) terminates; the raw variant
 * needs the next case to START within those 5 s of a 100 ms timeout. That is the only wall-clock
 * margin in these proofs; if the host ever breaks it, the raw-variant test fails saying the planted
 * scenario did not cascade, not the containment test. */
describe("an abandoned test costs one red, and a leaked act() scope is named", () => {
  const HELPER = resolve(PKG, "src", "test-support", "act-turns.ts").split("\\").join("/");

  /** The planted drive: a store, a view, one abandoned case, and cases that must each commit. */
  const planted = (asyncAct: string, preamble: string): string =>
    [
      `import { createRequire } from "node:module";`,
      preamble,
      `const req = createRequire(${JSON.stringify(pathToFileURL(resolve(PKG, "package.json")).href)});`,
      `const { createElement, useState } = req("react");`,
      `const { createRoot } = req("react-dom/client");`,
      `(globalThis as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT = true;`,
      /* A default-lane state update, as the app's own effects make: React schedules it through the act
         queue, so it commits only when an outermost act() scope closes. */
      `let value = 0;`,
      `let setShown = (_: number): void => {};`,
      `const set = (v: number): void => { value = v; setShown(v); };`,
      `function View() { const [v, setV] = useState(0); setShown = setV; return createElement("output", null, String(v)); }`,
      `const container = document.createElement("div");`,
      `document.body.append(container);`,
      `const root = createRoot(container);`,
      `let ranOnPastScope = false;`,
      `let timerScopeOpened = false;`,
      `let release = (): void => {};`,
      `const gate = new Promise<void>((r) => { release = r; });`,
      `const sleep = (ms: number) => new Promise<void>((r) => setTimeout(r, ms));`,
      `beforeAll(async () => { await ${asyncAct}(async () => { root.render(createElement(View)); }); });`,
      `const show = async (n: number, opensGate = false): Promise<void> => {`,
      `  await ${asyncAct}(async () => { if (opensGate) { release(); await sleep(50); } set(n); });`,
      `  expect(container.textContent).toBe(String(n));`,
      `};`,
      `it("case 1", async () => { await show(1); });`,
      /* Parked in a scope when the runner abandons it; then a bare timer the helper cannot see; then
         another scope that would land inside a later case. */
      `it("ABANDONED", { timeout: 100 }, async () => {`,
      `  setTimeout(release, 5000);`,
      `  await ${asyncAct}(async () => { await gate; });`,
      /* Plain, synchronous work right after the scope closes: only the checkpoint after a scope stops it. */
      `  ranOnPastScope = true;`,
      `  await sleep(200);`,
      `  await ${asyncAct}(async () => { set(-1); });`,
      `  expect(value).toBe(-1);`,
      `});`,
      /* Opens its own scope first, THEN lets the abandoned one close inside it: the out-of-order close. */
      `it("case 3", async () => { await show(3, true); });`,
      ...[4, 5].map((n) => `it("case ${n}", async () => { await show(${n}); });`),
      /* Abandoned while in a bare timer the helper cannot see, then opens a scope that would land inside a
         later case: only the checkpoint before a scope stops it. Its timer expires before case 9's does. */
      `it("ABANDONED IN A TIMER", { timeout: 100 }, async () => {`,
      `  await sleep(300);`,
      `  await ${asyncAct}(async () => { timerScopeOpened = true; set(-2); });`,
      `});`,
      ...[6, 7, 8].map((n) => `it("case ${n}", async () => { await show(${n}); });`),
      /* Outlasts the abandoned body's bare timer: had its continuation not been stopped at the checkpoint,
         its second scope would have landed by now and set -1. */
      `it("case 9", async () => {`,
      `  await ${asyncAct}(() => sleep(400));`,
      `  expect(ranOnPastScope, "ABANDONED ran on after its scope closed (the checkpoint after a scope)").toBe(false);`,
      `  expect(timerScopeOpened, "ABANDONED IN A TIMER opened a scope in a later case (the checkpoint before a scope)").toBe(false);`,
      `  expect(value).toBe(8);`,
      `  expect(container.textContent).toBe("8");`,
      `});`,
    ].join("\n");

  const CASES = ["case 1", "ABANDONED", "case 3", "case 4", "case 5", "ABANDONED IN A TIMER", "case 6", "case 7", "case 8", "case 9"];

  interface Assertion {
    title: string;
    status: string;
    failureMessages: string[];
  }

  function runPlanted(): { byFile: Map<string, Map<string, Assertion>>; output: string; exit: number } {
    const dir = mkdtempSync(join(tmpdir(), "atlas-act-"));
    try {
      const configUrl = pathToFileURL(resolve(PKG, "vitest.config.ts")).href;
      writeFileSync(
        join(dir, "planted.vitest.config.mts"),
        [
          `import base from ${JSON.stringify(configUrl)};`,
          "const b = base as { test?: Record<string, unknown> } & Record<string, unknown>;",
          // Everything of the real config (setupFiles and the jsdom environment included) except where and what to collect.
          /* jsdom transforms in web mode, which only serves files under `server.fs.allow`: the setup file and the
             helper live in this package, the planted files in the temporary root. */
          `export default { ...b, root: ${JSON.stringify(dir)}, server: { fs: { allow: [${JSON.stringify(PKG)}, ${JSON.stringify(dir)}] } }, test: { ...b.test, include: ["*.planted.test.ts"], exclude: [] } };`,
        ].join("\n"),
      );
      writeFileSync(join(dir, "contained.planted.test.ts"), planted("actAsync", `import { actAsync } from ${JSON.stringify(HELPER)};`));
      writeFileSync(
        join(dir, "raw.planted.test.ts"),
        planted("act", `const act = createRequire(${JSON.stringify(pathToFileURL(resolve(PKG, "package.json")).href)})("react").act;`),
      );
      writeFileSync(
        join(dir, "canary.planted.test.ts"),
        [
          `import { createRequire } from "node:module";`,
          `import { actAsync } from ${JSON.stringify(HELPER)};`,
          `const { act } = createRequire(${JSON.stringify(pathToFileURL(resolve(PKG, "package.json")).href)})("react");`,
          `(globalThis as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT = true;`,
          `it("CLEAN", async () => { await actAsync(async () => {}); expect(1).toBe(1); });`,
          `it("THROWING", () => { expect(() => act(() => { throw new Error("thrown inside act"); })).toThrow("thrown inside act"); });`,
          `it("LEAKS", () => { void act(async () => {}); expect(1).toBe(1); });`,
        ].join("\n"),
      );
      const out = join(dir, "result.json");
      let exit = 0;
      let output = "";
      try {
        output = execFileSync(
          process.execPath,
          [resolve(PKG, "node_modules", "vitest", "vitest.mjs"), "run", "--config", join(dir, "planted.vitest.config.mts"), "--reporter=json", `--outputFile=${out}`],
          { cwd: dir, encoding: "utf8", stdio: "pipe", env: { ...process.env, VITE_CONFIG_NATIVE_IGNORE_WARNING: "true" } },
        );
      } catch (e) {
        const err = e as { status?: number; stdout?: string; stderr?: string };
        exit = err.status ?? -1;
        output = `${err.stdout ?? ""}\n${err.stderr ?? ""}`;
      }
      const report = existsSync(out)
        ? (JSON.parse(readFileSync(out, "utf8")) as { testResults: { name: string; message?: string; assertionResults: Assertion[] }[] })
        : { testResults: [] };
      const byFile = new Map(
        report.testResults.map((f) => [f.name.split(/[\\/]/).pop()!.replace(".planted.test.ts", ""), new Map(f.assertionResults.map((a) => [a.title, a]))]),
      );
      const fileErrors = report.testResults.map((f) => f.message ?? "").filter((m) => m !== "").join("\n");
      return { byFile, output: `${fileErrors}\n${output}`, exit };
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  }

  let run: ReturnType<typeof runPlanted> | null = null;
  const result = (): ReturnType<typeof runPlanted> => (run ??= runPlanted());

  it("the child run collected all three planted files, each case by name", () => {
    const { byFile, exit, output } = result();
    expect(exit, `the child run must fail (each planted file holds a failing case):\n${output.slice(-4000)}`).toBe(1);
    expect([...byFile.keys()].sort(), output.slice(-4000)).toEqual(["canary", "contained", "raw"]);
    expect([...byFile.get("contained")!.keys()], output.slice(0, 4000)).toEqual(CASES);
    expect([...byFile.get("raw")!.keys()], output.slice(0, 4000)).toEqual(CASES);
    expect([...byFile.get("canary")!.keys()], output.slice(0, 4000)).toEqual(["CLEAN", "THROWING", "LEAKS"]);
  }, 120_000);

  it("contained: each abandoned case is ONE red; every later case still commits", () => {
    const contained = result().byFile.get("contained")!;
    const failed = [...contained.values()].filter((a) => a.status !== "passed").map((a) => a.title);
    expect(failed, [...contained.values()].map((a) => `${a.title}: ${a.status} ${a.failureMessages.join(" | ").slice(0, 400)}`).join("\n")).toEqual([
      "ABANDONED",
      "ABANDONED IN A TIMER",
    ]);
    for (const t of ["ABANDONED", "ABANDONED IN A TIMER"]) expect(contained.get(t)!.failureMessages.join("\n"), t).not.toMatch(/\[act-scope guard\]/);
  }, 120_000);

  it("raw: the same planted file with raw act() cascades, and the canary names why", () => {
    const raw = result().byFile.get("raw")!;
    const later = ["case 4", "case 5", "case 6", "case 7", "case 8", "case 9"].map((t) => raw.get(t)!);
    expect(later.map((a) => a.status), "the planted scenario is live: without the helper, later cases stop committing").toEqual(
      later.map(() => "failed"),
    );
    expect(later.every((a) => a.failureMessages.some((m) => m.includes("[act-scope guard]"))), "the canary names the leak on each").toBe(true);
    expect(raw.get("case 1")!.status).toBe("passed");
  }, 120_000);

  it("canary: an un-awaited act() scope fails the test that left it; a thrown act() residue does not", () => {
    const canary = result().byFile.get("canary")!;
    expect(canary.get("CLEAN")!.status).toBe("passed");
    expect(canary.get("THROWING")!.status, canary.get("THROWING")!.failureMessages.join("\n")).toBe("passed");
    expect(canary.get("LEAKS")!.status).toBe("failed");
    expect(canary.get("LEAKS")!.failureMessages.join("\n")).toMatch(/\[act-scope guard\] React's act\(\) queue is still open after this test ended/);
  }, 120_000);
});

/* ── the whole-program builds in THIS file run where the detector does not judge them (F2, R7-V2-5) ──
 * MEASURED (independent verifier R7-V2-5, 12 busy loops on the shared 14-core host): 'tsconfig.config.json
 * reads both configs and is clean under strict' timed out at the 30 s hang detector, because it built a
 * whole ts.createProgram over Vite's and Vitest's types and checked it INSIDE the test body. That is the
 * indivisible whole-program unit source-hygiene.test.ts moved into a beforeAll with its stated
 * PROGRAM_BUILD_LIMIT; the detector is not raised for a test. The rule is checked here as a class, over
 * this file's own source: every `ts.createProgram` call lies lexically inside a `beforeAll(…,
 * PROGRAM_BUILD_LIMIT)` callback, or inside a function whose every call does. A build anywhere else — a test
 * body, a describe body run at collection, a helper a test calls — is named with its line. */
describe("every whole-program build in this file runs in a beforeAll under PROGRAM_BUILD_LIMIT", () => {
  const SELF = fileURLToPath(import.meta.url);
  const misplacedBuilds = (text: string): string[] => {
    const sf = ts.createSourceFile(SELF, text, ts.ScriptTarget.Latest, true, ts.ScriptKind.TS);
    const isCreateProgram = (n: ts.Node): n is ts.CallExpression =>
      ts.isCallExpression(n) && ts.isPropertyAccessExpression(n.expression) && n.expression.name.text === "createProgram";
    /** Inside the callback of `beforeAll(cb, PROGRAM_BUILD_LIMIT)`. */
    const inBoundedHook = (n: ts.Node): boolean => {
      for (let p: ts.Node | undefined = n.parent; p !== undefined; p = p.parent) {
        if (!ts.isCallExpression(p) || !ts.isIdentifier(p.expression) || p.expression.text !== "beforeAll") continue;
        const [cb, limit] = p.arguments;
        if (cb !== undefined && n.pos >= cb.pos && n.end <= cb.end && limit !== undefined && ts.isIdentifier(limit) && limit.text === "PROGRAM_BUILD_LIMIT") return true;
      }
      return false;
    };
    /** The named function (declaration, or a const bound to an arrow/function) `n` sits in, if any. */
    const enclosingNamed = (n: ts.Node): string | null => {
      for (let p: ts.Node | undefined = n.parent; p !== undefined; p = p.parent) {
        if (ts.isFunctionDeclaration(p) && p.name !== undefined) return p.name.text;
        if ((ts.isArrowFunction(p) || ts.isFunctionExpression(p)) && ts.isVariableDeclaration(p.parent) && ts.isIdentifier(p.parent.name)) return p.parent.name.text;
      }
      return null;
    };
    const callsOf = (name: string): ts.CallExpression[] => {
      const out: ts.CallExpression[] = [];
      const visit = (n: ts.Node): void => {
        if (ts.isCallExpression(n) && ts.isIdentifier(n.expression) && n.expression.text === name) out.push(n);
        ts.forEachChild(n, visit);
      };
      visit(sf);
      return out;
    };
    const line = (n: ts.Node): number => sf.getLineAndCharacterOfPosition(n.getStart(sf)).line + 1;
    /** Bounded: in the hook itself, or in a named function every one of whose calls is (one level of indirection per step, cycle-safe). */
    const bounded = (n: ts.Node, seen: ReadonlySet<string> = new Set()): boolean => {
      if (inBoundedHook(n)) return true;
      const fn = enclosingNamed(n);
      if (fn === null || seen.has(fn)) return false;
      const calls = callsOf(fn);
      return calls.length > 0 && calls.every((c) => bounded(c, new Set([...seen, fn])));
    };
    const out: string[] = [];
    const visit = (n: ts.Node): void => {
      if (isCreateProgram(n) && !bounded(n)) out.push(`line ${line(n)}: ${n.getText(sf).replace(/\s+/g, " ").slice(0, 70)}`);
      ts.forEachChild(n, visit);
    };
    visit(sf);
    return out;
  };

  it("finds this file's program builds, and none is outside the bounded hook", () => {
    const text = readFileSync(SELF, "utf8");
    expect((text.match(/\bts\.createProgram\(/g) ?? []).length, "the rule reads nothing: no program build in this file").toBeGreaterThan(3);
    expect(misplacedBuilds(text), "a whole-program build the 30 s detector would judge").toEqual([]);
  });

  it("is live: a build in a test body, at collection, and in a helper a test calls are each named", () => {
    const planted = [
      "const L = 1;",
      'it("t", () => { ts.createProgram([], {}); });',
      'describe("d", () => { const p = ts.createProgram([], {}); });',
      "function helper(): void { ts.createProgram([], {}); }",
      'it("u", () => { helper(); });',
      "function fine(): void { ts.createProgram([], {}); }",
      "beforeAll(() => { fine(); ts.createProgram([], {}); }, PROGRAM_BUILD_LIMIT);",
      "beforeAll(() => { ts.createProgram([], {}); }, 30_000);",
    ].join("\n");
    expect(misplacedBuilds(planted).map((s) => s.replace(/:.*/, ""))).toEqual(["line 2", "line 3", "line 4", "line 8"]);
  });
});
