/**
 * tracked-sources.test.ts — what the gates measure must be something a commit can reproduce.
 *
 * WHAT WAS WRONG (critic F5, 2026-09-22). The repository held ONE commit, and 55 files under `src/`
 * were untracked — among them two of the compiled data files (`src/forwarding/acl-bindings.json`,
 * `src/forwarding/rib-evidence.json`) and runtime modules the build imports (`src/mount.tsx`, the
 * chunk `main.tsx` loads; `forwarding/bindings.ts`; `fabric3d/stepdown.ts`; …). Every byte-compare
 * `provenance.test.ts` performs and every capture `review/capture.mjs` takes was a property of that
 * working tree, not of any commit, and a clean checkout could not have reproduced any of it. No
 * gate could see this: each one reads files off disk, and an untracked file reads exactly like a
 * committed one.
 *
 * THE CLASS, derived rather than listed: every file reachable from the page's entry through
 * static or dynamic imports (the module graph the build bundles — code, JSON, CSS), plus every
 * `tools/compile-*.mjs` that produces the compiled data. A hand-maintained list of "the important
 * files" is the defect shape this repository keeps finding; the graph cannot drift from the build
 * because it is read from the same import statements the build reads.
 *
 * WHAT THIS DOES NOT CHECK. That the tracked copy EQUALS the working copy. A modified tracked file
 * is ordinary development and would make this gate red on every edit; an UNTRACKED one is a file
 * no commit has ever held, which is the property the finding names. Reproducing a measurement from
 * a specific sha is still the reader's job: check out the sha and re-run.
 *
 * WHEN THIS IS RED. Nothing in the code is wrong: the fix is to commit the listed files. That is
 * the repository owner's decision, so this gate reports it rather than doing it — and it must not
 * be weakened into a skip to make a suite green, because an unverifiable reproduction claim that
 * keeps being made is exactly the false-health shape this codebase exists to refuse.
 */
import { execFileSync } from "node:child_process";
import { existsSync, readdirSync, readFileSync, statSync } from "node:fs";
import { dirname, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import ts from "typescript";
import { describe, expect, it } from "vitest";

const HERE = dirname(fileURLToPath(import.meta.url));
const PKG = resolve(HERE, "..", ".."); // atlas-scope/

const posix = (abs: string): string => relative(PKG, abs).split("\\").join("/");

/** Every module specifier a file names: `import … from`, `export … from`, `import()`, bare `import "x"`. */
export function specifiersOf(file: string, text: string): string[] {
  const sf = ts.createSourceFile(file, text, ts.ScriptTarget.ES2023, true, file.endsWith("x") ? ts.ScriptKind.TSX : ts.ScriptKind.TS);
  const out: string[] = [];
  const visit = (n: ts.Node): void => {
    if ((ts.isImportDeclaration(n) || ts.isExportDeclaration(n)) && n.moduleSpecifier && ts.isStringLiteral(n.moduleSpecifier)) {
      // A type-only import is erased by the build and does not reach the bundle.
      const typeOnly = ts.isImportDeclaration(n) ? n.importClause?.isTypeOnly === true : n.isTypeOnly;
      if (!typeOnly) out.push(n.moduleSpecifier.text);
    }
    if (ts.isCallExpression(n) && n.expression.kind === ts.SyntaxKind.ImportKeyword) {
      const a = n.arguments[0];
      if (a !== undefined && (ts.isStringLiteral(a) || ts.isNoSubstitutionTemplateLiteral(a))) out.push(a.text);
    }
    ts.forEachChild(n, visit);
  };
  visit(sf);
  return out;
}

const EXTENSIONS = ["", ".ts", ".tsx", ".js", ".mjs", "/index.ts", "/index.tsx"];

function resolveLocal(from: string, spec: string): string | null {
  if (!spec.startsWith(".") && !spec.startsWith("/")) return null; // a package, owned by the lockfile
  const base = spec.startsWith("/") ? resolve(PKG, `.${spec}`) : resolve(dirname(from), spec);
  const clean = base.replace(/\?.*$/, "");
  for (const ext of EXTENSIONS) {
    const p = clean + ext;
    if (existsSync(p) && statSync(p).isFile()) return p;
  }
  throw new Error(`${posix(from)} imports "${spec}", which resolves to no file`);
}

/** The module graph the page loads, walked from index.html's module script. */
export function runtimeGraph(): string[] {
  const html = readFileSync(resolve(PKG, "index.html"), "utf8");
  const entries = [...html.matchAll(/<script[^>]*type="module"[^>]*src="([^"]+)"/g)].map((m) => resolveLocal(resolve(PKG, "index.html"), m[1]!));
  const seen = new Set<string>();
  const queue = entries.filter((e): e is string => e !== null);
  while (queue.length > 0) {
    const f = queue.pop()!;
    if (seen.has(f)) continue;
    seen.add(f);
    if (!/\.(tsx?|m?js)$/.test(f)) continue; // JSON and CSS are leaves
    for (const spec of specifiersOf(f, readFileSync(f, "utf8"))) {
      const r = resolveLocal(f, spec);
      if (r !== null) queue.push(r);
    }
  }
  return [...seen].map(posix).sort();
}

const compilers = (): string[] =>
  readdirSync(resolve(PKG, "tools"))
    .filter((n) => /^compile-.*\.mjs$/.test(n))
    .map((n) => `tools/${n}`)
    .sort();

function untracked(paths: readonly string[]): string[] {
  let out: string;
  try {
    out = execFileSync("git", ["ls-files", "--others", "-z", "--", ...paths], {
      cwd: PKG,
      encoding: "utf8",
    });
  } catch (e) {
    throw new Error(`git could not be asked which files are tracked, so reproducibility is unverifiable: ${String(e)}`);
  }
  return out.split("\0").filter((s) => s.length > 0).sort();
}

describe("everything the build imports and the compilers produce is under version control", () => {
  it("the walk reaches the real application, not an empty or entry-only set", () => {
    const g = runtimeGraph();
    // Anchored to modules that exist today and that no refactor can make optional.
    expect(g).toContain("src/main.tsx");
    expect(g).toContain("src/data/fabric.json");
    expect(g.some((f) => f.startsWith("src/forwarding/"))).toBe(true);
    expect(g.some((f) => f.startsWith("src/fabric3d/"))).toBe(true);
    expect(g.length).toBeGreaterThan(40);
    expect(compilers()).toContain("tools/compile-snapshot.mjs");
  });

  it("the detector parses the import forms the build follows", () => {
    const src = [
      'import a from "./a";',
      'import "./side.css";',
      'export { b } from "./b";',
      'const c = import("./c");',
      'import type { T } from "./types-only";',
      'import React from "react";',
    ].join("\n");
    expect(specifiersOf("x.tsx", src)).toEqual(["./a", "./side.css", "./b", "./c", "react"]);
  });

  it("no runtime-imported module, compiled file or compiler is untracked", () => {
    const graph = runtimeGraph();
    const missing = untracked([...graph, ...compilers()]);
    expect(
      missing,
      "these files are loaded by the build or produce its data, and no commit has ever held them —\n" +
        "every gate that reads them measures this working tree, not a reproducible revision.\n" +
        "The fix is to COMMIT them (the repository owner's decision), not to weaken this test:\n" +
        missing.join("\n"),
    ).toEqual([]);
  });
});
