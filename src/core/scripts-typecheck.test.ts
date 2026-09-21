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
import { existsSync, readFileSync } from "node:fs";
import { dirname, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";
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

  it("names what it does not cover, rather than implying it does", () => {
    // `e2e` is declared in tsconfig.json's include and in an npm script, and does not exist.
    // Asserted so the next person reads it here instead of rediscovering it.
    expect(existsSync(resolve(PKG, "e2e"))).toBe(false);
    const scripts = readFileSync(CONFIG, "utf8");
    expect(scripts).toContain("review/*.mjs");
  });
});
