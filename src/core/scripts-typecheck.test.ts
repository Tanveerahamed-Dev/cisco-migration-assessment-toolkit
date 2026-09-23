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
import { describe, expect, it } from "vitest";

const PKG = resolve(dirname(fileURLToPath(import.meta.url)), "..", "..");
const CONFIG = resolve(PKG, "tsconfig.scripts.json");

function check(): { files: string[]; diagnostics: string[] } {
  const raw = ts.readConfigFile(CONFIG, (p) => readFileSync(p, "utf8"));
  expect(raw.error, `tsconfig.scripts.json could not be read`).toBeUndefined();
  const parsed = ts.parseJsonConfigFileContent(raw.config, ts.sys, PKG, undefined, CONFIG);
  expect(
    parsed.errors.filter((d) => d.category === ts.DiagnosticCategory.Error).map((d) => d.messageText),
  ).toEqual([]);

  const program = ts.createProgram(parsed.fileNames, parsed.options);
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
  };
}

describe("the build scripts are inside a type-checking gate", () => {
  const result = check();

  it("checks the scripts the main config only appears to cover", () => {
    /* The denominator, pinned. An empty file list would make the assertion below vacuous, which is
       exactly the shape of the defect this file answers. */
    expect(result.files).toContain("tools/compile-snapshot.mjs");
    expect(result.files.every((f) => f.endsWith(".mjs"))).toBe(true);
    expect(result.files.length).toBeGreaterThan(0);
  });

  it("reports no type error in them", () => {
    expect(result.diagnostics, `type errors in the build scripts:\n${result.diagnostics.join("\n")}`).toEqual(
      [],
    );
  });

  it("is checking JavaScript, not silently skipping it", () => {
    /* A `checkJs: false` typo would make the gate above pass over any file at all. Plant a real
       error in memory and confirm the same settings report it. */
    const raw = ts.readConfigFile(CONFIG, (p) => readFileSync(p, "utf8"));
    const parsed = ts.parseJsonConfigFileContent(raw.config, ts.sys, PKG, undefined, CONFIG);
    const planted = resolve(PKG, "tools", "__typecheck_liveness.mjs");
    const source = "const n = 1;\nn.toFixed(2, 3, 4);\nexport default n;\n";

    const host = ts.createCompilerHost(parsed.options, true);
    const readFile = host.readFile.bind(host);
    host.readFile = (f) => (resolve(f) === planted ? source : readFile(f));
    host.fileExists = ((orig) => (f: string) => resolve(f) === planted || orig(f))(
      host.fileExists.bind(host),
    );

    const program = ts.createProgram([planted], parsed.options, host);
    const found = program
      .getSemanticDiagnostics()
      .map((d) => ts.flattenDiagnosticMessageText(d.messageText, " "));
    expect(found.join(" "), "the same settings must reject a real error in a .mjs file").toMatch(
      /Expected 0-1 arguments|Expected 1 arguments/,
    );
    // ...and the planted file was never written to disk.
    expect(existsSync(planted)).toBe(false);
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

    const strictProgram = ts.createProgram(parsed.fileNames, { ...parsed.options, noImplicitAny: true });
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

  it("tsconfig.config.json reads both configs and is clean under strict", () => {
    const p = projects().find((x) => x.name === "tsconfig.config.json")!;
    expect(p.parsed.fileNames.map(posixRel).sort()).toEqual(["vite.config.ts", "vitest.config.ts"]);
    expect(p.parsed.options.strict).toBe(true);
    expect(p.parsed.options.noUncheckedIndexedAccess).toBe(true);
    const found = diagnosticsOf(ts.createProgram(p.parsed.fileNames, p.parsed.options));
    expect(found, `type errors in the runner/bundler configs:\n${found.join("\n")}`).toEqual([]);
  });

  it("is live: the dead option and a type error, planted back in memory, are both reported", () => {
    /* The exact defect, restored in memory only, plus a plain type error in the build config: a gate
       whose failure path never ran is not a gate. The files on disk are never written. */
    const p = projects().find((x) => x.name === "tsconfig.config.json")!;
    const vitestCfg = resolve(PKG, "vitest.config.ts");
    const viteCfg = resolve(PKG, "vite.config.ts");
    const vitestText = readFileSync(vitestCfg, "utf8");
    expect(vitestText).toMatch(/maxWorkers: WORKERS,/);
    const planted = new Map<string, string>([
      [vitestCfg, vitestText.replace("maxWorkers: WORKERS,", "maxWorkers: WORKERS,\n      minWorkers: 1,")],
      [viteCfg, `${readFileSync(viteCfg, "utf8")}\nexport const planted: number = "not a number";\n`],
    ]);
    const host = ts.createCompilerHost(p.parsed.options, true);
    const readFile = host.readFile.bind(host);
    host.readFile = (f) => planted.get(resolve(f)) ?? readFile(f);
    const found = diagnosticsOf(ts.createProgram(p.parsed.fileNames, p.parsed.options, host)).join("\n");
    expect(found).toMatch(/vitest\.config\.ts:\d+ TS2769 .*minWorkers/);
    expect(found).toMatch(/vite\.config\.ts:\d+ TS2322/);
  });
});

/* ── the runtime assertion guard (acceptance F2) ─────────────────────────────────────────────────
 * src/test-setup.ts fails any test that makes zero assertions WHEN IT RUNS. These tests prove it is
 * installed by the real config, that it really fails such a test and names it, that it leaves an
 * asserting test alone, and that its one opt-out is explicit and justified wherever it is used. */
describe("every test makes at least one assertion when it runs", () => {
  it("the guard ran in this very worker (the real config's setupFiles installed it)", () => {
    expect((globalThis as Record<symbol, unknown>)[Symbol.for("atlas-scope.assertion-guard.installed")]).toBe(true);
    expect(readFileSync(resolve(PKG, "vitest.config.ts"), "utf8")).toMatch(/setupFiles:\s*\[fileURLToPath\(new URL\("\.\/src\/test-setup\.ts"/);
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
