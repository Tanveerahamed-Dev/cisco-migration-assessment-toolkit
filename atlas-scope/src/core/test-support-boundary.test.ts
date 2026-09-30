// @vitest-environment node
/**
 * test-support-boundary.test.ts — test-only code lives in src/test-support/, and nothing a build can
 * reach imports it.
 *
 * WHAT WAS WRONG (phase 3.5 close-out). Test-only data modules — the golden expectations, the panels'
 * flow universe, the source-snapshot reader, the forwarding subject helpers — sat beside product modules
 * in bundleable folders (src/forwarding/, src/panels/, src/core/dataset/). Nothing distinguished them
 * from product code but a comment, so AssessHub's build-evidence scan
 * (webapp/tests/test_scope_mount.py, "no module a runtime build can bundle reads as snapshot evidence")
 * had to read them as bundleable, and one of them binds literal snapshot citations. The boundary was a
 * convention; this file makes it structural.
 *
 * THE RULE, over the import graph derived from the tree (never a list of file names):
 *   1. No module outside src/test-support/ that is not a `*.test.*` file imports anything under
 *      src/test-support/ — by static import, re-export, dynamic import(), `import.meta.glob`, or a
 *      `new URL("…", import.meta.url)` asset reference (with comments between the tokens read as the
 *      trivia they are) — and no Vite configuration a build loads (the default vite.config.* and any file
 *      a package script passes with --config/-c) names a path under it in any string literal: its inputs
 *      (rollupOptions.input, a plugin's path) are plain strings, never imports. src/ and tools/lib/ are
 *      both read.
 *   2. Every non-test module that a test reaches but no product entry (the module scripts of every HTML
 *      page at the package root, the workers they start, and the build configurations) reaches is
 *      test-only, and must therefore live under src/test-support/. A new test helper written beside
 *      product code fails here by name.
 *   3. No product entry's closure contains a src/test-support/ module (1 implies it; asserted directly).
 * The planted tree below runs THIS graph function over each import form, so a regression in the scan's
 * own edge detection turns it red instead of passing on a blind scan.
 *
 * AssessHub's Python test proves rule 1 again with its own parser rather than trusting this file: it
 * excludes src/test-support/ from the evidence scan only after that proof holds.
 */
import { globSync, mkdirSync, mkdtempSync, readdirSync, readFileSync, rmSync, statSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import ts from "typescript";
import { describe, expect, it } from "vitest";

const PKG = resolve(dirname(fileURLToPath(import.meta.url)), "..", "..");
const posix = (p: string): string => p.split("\\").join("/");

const OPTIONS: ts.CompilerOptions = {
  module: ts.ModuleKind.ESNext,
  moduleResolution: ts.ModuleResolutionKind.Bundler,
  allowImportingTsExtensions: true,
  resolveJsonModule: true,
  jsx: ts.JsxEmit.ReactJSX,
  noEmit: true,
};

interface Edge {
  from: string;
  to: string;
  via: "import" | "import.meta.glob" | "new URL" | "build config";
}

interface ModuleGraph {
  /** Every module under src/, root-relative POSIX. */
  modules: string[];
  edges: Edge[];
  /** The module scripts of every HTML page at the package root, and every Vite configuration a build
      loads, root-relative POSIX. */
  entries: string[];
}

/* Other source the build reads outside src/: its edges are followed, but its files are not app modules. */
const EDGE_ONLY_ROOTS = ["tools/lib"];
const DEFAULT_CONFIGS = ["js", "mjs", "ts", "cjs", "mts", "cts"].map((ext) => `vite.config.${ext}`);
const BOUNDARY_NAME = /(?:^|[\\/])test-support(?:[\\/]|$)/;

/** The Vite configurations a build loads, from the package itself: the default file Vite looks for at the
    root, and every file a package.json script hands Vite with --config/-c. Root-relative POSIX. */
function buildConfigs(root: string): string[] {
  const found = new Set(DEFAULT_CONFIGS);
  const manifest = join(root, "package.json");
  let scripts: Record<string, unknown> = {};
  try {
    scripts = (JSON.parse(readFileSync(manifest, "utf8")) as { scripts?: Record<string, unknown> }).scripts ?? {};
  } catch {
    scripts = {};
  }
  for (const command of Object.values(scripts)) {
    if (typeof command !== "string" || !/(?:^|[\s&|;])vite\b/.test(command)) continue;
    for (const m of command.matchAll(/(?:^|\s)(?:--config|-c)(?:=|\s+)(["']?)([^\s"']+)\1/g)) found.add(posix(m[2]!));
  }
  return [...found].filter((rel) => {
    try {
      return statSync(join(root, rel)).isFile();
    } catch {
      return false;
    }
  }).sort();
}

/** A configuration's inputs are plain strings (rollupOptions.input, a plugin's path): every literal in it
    that names the boundary directory is an edge, however it is joined, read against the package root. */
function configEdges(root: string, rel: string, text: string): Edge[] {
  const sf = ts.createSourceFile(rel, text, ts.ScriptTarget.ES2023, true, ts.ScriptKind.TS);
  const out: Edge[] = [];
  const visit = (n: ts.Node): void => {
    if (ts.isStringLiteralLike(n) && BOUNDARY_NAME.test(n.text)) {
      out.push({ from: rel, to: posix(relative(root, resolve(root, n.text.replace(/^[\\/]+/, "")))), via: "build config" });
    }
    ts.forEachChild(n, visit);
  };
  visit(sf);
  return out;
}

const SUPPORT = "src/test-support/";
const isTestFile = (rel: string): boolean => /\.test\.[cm]?[jt]sx?$/.test(rel);
/* The directory itself counts: an expanded specifier's first piece can name only the directory. */
const isSupport = (rel: string): boolean => rel === SUPPORT.slice(0, -1) || rel.startsWith(SUPPORT);
const isCode = (name: string): boolean => /\.[cm]?[jt]sx?$/.test(name) && !name.endsWith(".d.ts");
const literalsOf = (n: ts.Node): string[] =>
  ts.isStringLiteralLike(n) ? [n.text] : ts.isArrayLiteralExpression(n) ? n.elements.flatMap(literalsOf) : [];

/** The first literal piece of a specifier assembled at run time: a template's head, or the leftmost operand
    of a `+` chain; null when it starts with anything else (a variable, a call). */
function firstPiece(n: ts.Expression): string | null {
  if (ts.isParenthesizedExpression(n)) return firstPiece(n.expression);
  if (ts.isStringLiteralLike(n)) return n.text;
  if (ts.isTemplateExpression(n)) return n.head.text;
  if (ts.isBinaryExpression(n) && n.operatorToken.kind === ts.SyntaxKind.PlusToken) return firstPiece(n.left);
  return null;
}

/** Every file one module's text reaches, by every form Vite resolves to a file. */
function edgesOf(root: string, absPath: string, text: string): Edge[] {
  const here = dirname(absPath);
  const from = posix(relative(root, absPath));
  const out: Edge[] = [];
  const target = (spec: string): string | null => {
    const clean = spec.replace(/[?#].*$/, "");
    if (clean.startsWith("/")) return resolve(root, `.${clean}`);
    if (!clean.startsWith(".")) return null; // a package: owned by the lockfile
    const resolved = ts.resolveModuleName(clean, absPath, OPTIONS, ts.sys).resolvedModule?.resolvedFileName;
    return resolved ?? resolve(here, clean); // unresolved (CSS, a missing file): its path still names where it points
  };
  const push = (abs: string | null, via: Edge["via"]): void => {
    if (abs !== null) out.push({ from, to: posix(relative(root, abs)), via });
  };
  for (const f of ts.preProcessFile(text, true, true).importedFiles) push(target(f.fileName), "import");
  if (/\bimport\b|\bURL\b/.test(text)) {
    const sf = ts.createSourceFile(absPath, text, ts.ScriptTarget.ES2023, true, absPath.endsWith("x") ? ts.ScriptKind.TSX : ts.ScriptKind.TS);
    const visit = (n: ts.Node): void => {
      /* A dynamic import Vite expands from pieces: read by its first literal piece (a literal specifier is
         preProcessFile's, above). */
      if (ts.isCallExpression(n) && n.expression.kind === ts.SyntaxKind.ImportKeyword && n.arguments[0] && !ts.isStringLiteralLike(n.arguments[0])) {
        const head = firstPiece(n.arguments[0]);
        if (head !== null) push(target(head), "import");
      }
      if (ts.isCallExpression(n) && ts.isPropertyAccessExpression(n.expression) && n.expression.getText(sf).replace(/\s/g, "") === "import.meta.glob") {
        for (const pattern of n.arguments[0] ? literalsOf(n.arguments[0]) : []) {
          if (pattern.startsWith("!")) continue;
          for (const m of globSync(pattern, { cwd: here })) push(resolve(here, m), "import.meta.glob");
        }
      }
      if (ts.isNewExpression(n) && n.expression.getText(sf) === "URL" && n.arguments?.[0] && ts.isStringLiteralLike(n.arguments[0])) {
        push(target(n.arguments[0].text), "new URL");
      }
      ts.forEachChild(n, visit);
    };
    visit(sf);
  }
  return out;
}

/** The import graph of `root`'s src/ tree and the entries of its HTML pages. */
function moduleGraph(root: string): ModuleGraph {
  const modules: string[] = [];
  const edges: Edge[] = [];
  const walk = (dir: string, asModules: boolean): void => {
    /* The entry's type comes from the directory read itself — no second stat of the path before it is read. Sorted by
       name in code-unit order, as `readdirSync(dir).sort()` was. */
    for (const entry of readdirSync(dir, { withFileTypes: true }).sort((a, b) => (a.name < b.name ? -1 : a.name > b.name ? 1 : 0))) {
      const name = entry.name;
      const p = join(dir, name);
      if (entry.isDirectory()) {
        if (name !== "node_modules") walk(p, asModules);
        continue;
      }
      if (!isCode(name)) continue;
      if (asModules) modules.push(posix(relative(root, p)));
      edges.push(...edgesOf(root, p, readFileSync(p, "utf8")));
    }
  };
  walk(join(root, "src"), true);
  for (const extra of EDGE_ONLY_ROOTS) {
    let isDir = false;
    try {
      isDir = statSync(join(root, extra)).isDirectory();
    } catch {
      isDir = false;
    }
    if (isDir) walk(join(root, extra), false);
  }
  const entries: string[] = [];
  for (const config of buildConfigs(root)) {
    const text = readFileSync(join(root, config), "utf8");
    entries.push(config);
    edges.push(...edgesOf(root, join(root, config), text), ...configEdges(root, config, text));
  }
  for (const page of readdirSync(root).filter((n) => n.endsWith(".html")).sort()) {
    for (const m of readFileSync(join(root, page), "utf8").matchAll(/<script\b[^>]*\bsrc="([^"]+)"/g)) {
      const src = m[1]!;
      if (src.startsWith("/")) entries.push(posix(relative(root, resolve(root, `.${src}`))));
    }
  }
  return { modules, edges, entries };
}

function closure(starts: Iterable<string>, edges: readonly Edge[]): Set<string> {
  const next = new Map<string, string[]>();
  for (const e of edges) next.set(e.from, [...(next.get(e.from) ?? []), e.to]);
  const seen = new Set<string>();
  const stack = [...starts];
  while (stack.length > 0) {
    const m = stack.pop()!;
    if (seen.has(m)) continue;
    seen.add(m);
    stack.push(...(next.get(m) ?? []));
  }
  return seen;
}

interface BoundaryReport {
  /** Rule 1: a non-test module outside the boundary reaching into it. */
  violations: string[];
  /** Rule 2: non-test modules a test reaches and no product entry does, living outside the boundary. */
  strays: string[];
  /** Rule 3: boundary modules inside a product entry's closure. */
  bundled: string[];
  productReach: Set<string>;
  testEdgesIntoSupport: number;
}

function boundaryReport(graph: ModuleGraph): BoundaryReport {
  const product = (m: string): boolean => !isTestFile(m) && !isSupport(m);
  const violations = graph.edges
    .filter((e) => product(e.from) && isSupport(e.to))
    .map((e) => `${e.from} -> ${e.to} (${e.via})`)
    .sort();
  const productReach = closure(graph.entries, graph.edges);
  const testReach = closure(graph.modules.filter(isTestFile), graph.edges);
  const known = new Set(graph.modules);
  const strays = [...testReach].filter((m) => known.has(m) && product(m) && !productReach.has(m)).sort();
  const bundled = [...productReach].filter(isSupport).sort();
  const testEdgesIntoSupport = graph.edges.filter((e) => isTestFile(e.from) && isSupport(e.to)).length;
  return { violations, strays, bundled, productReach, testEdgesIntoSupport };
}

describe("test-only code lives in src/test-support/ and no product module imports it", () => {
  const graph = moduleGraph(PKG);
  const report = boundaryReport(graph);

  it("the graph read the application from its real entries (non-vacuity)", () => {
    expect(graph.entries).toContain("src/main.tsx");
    /* The build's own configuration is read as an entry, not assumed to name nothing. */
    expect(graph.entries).toContain("vite.config.ts");
    expect(graph.modules.length).toBeGreaterThan(300);
    /* Every form the scan follows is live in the real tree: static and dynamic imports carry the app past
       main.tsx (mount.tsx is a dynamic import), and the compile worker is reached only by `new URL`. */
    expect(report.productReach.has("src/mount.tsx")).toBe(true);
    expect(report.productReach.has("src/core/dataset/compile.worker.ts")).toBe(true);
    expect(report.productReach.size).toBeGreaterThan(80);
    /* The boundary is in use, so a rule that found nothing found it by looking. */
    expect(report.testEdgesIntoSupport).toBeGreaterThan(30);
  });

  it("no non-test module outside src/test-support/ imports anything under it", () => {
    expect(report.violations).toEqual([]);
  });

  it("every module only tests reach lives under src/test-support/", () => {
    expect(report.strays, "test-only modules outside the boundary: move them into src/test-support/").toEqual([]);
  });

  it("no product entry's closure contains a src/test-support/ module", () => {
    expect(report.bundled).toEqual([]);
  });

  it("each import form, a stray helper and the entries are recognised by THIS graph (planted, not assumed)", () => {
    const dir = mkdtempSync(join(tmpdir(), "atlas-boundary-"));
    try {
      const put = (rel: string, text: string): void => {
        mkdirSync(dirname(join(dir, rel)), { recursive: true });
        writeFileSync(join(dir, rel), text);
      };
      put("index.html", '<!doctype html><script type="module" src="/src/main.tsx"></script>');
      put(
        "src/main.tsx",
        [
          'import "./static";',
          'const d = () => import("./dyn");',
          'const g = import.meta.glob("./globbed/*.ts");',
          'const w = new URL("./worker.ts", import.meta.url);',
          "export { d, g, w };",
        ].join("\n"),
      );
      put("src/static.ts", 'import { s } from "./test-support/s";\nexport const x = s;');
      put("src/dyn.ts", 'export const f = () => import("./test-support/d");');
      put("src/globbed/g.ts", 'export * from "../test-support/g";');
      put("src/worker.ts", 'const u = new URL("./test-support/w.ts", import.meta.url);\nexport { u };');
      put("src/helper.ts", "export const h = 1;");
      put("src/x.test.ts", 'import { h } from "./helper";\nimport { s } from "./test-support/s";\nexport { h, s };');
      put("src/test-support/s.ts", 'import { x } from "../static";\nexport const s = 1;\nexport { x };');
      put("src/test-support/d.ts", "export const d = 1;");
      put("src/test-support/g.ts", "export const g = 1;");
      put("src/test-support/w.ts", "export const w = 1;");
      const planted = boundaryReport(moduleGraph(dir));
      expect(planted.violations).toEqual(
        [
          "src/dyn.ts -> src/test-support/d.ts (import)",
          "src/globbed/g.ts -> src/test-support/g.ts (import)",
          "src/static.ts -> src/test-support/s.ts (import)",
          "src/worker.ts -> src/test-support/w.ts (new URL)",
        ].sort(),
      );
      expect(planted.strays).toEqual(["src/helper.ts"]);
      expect(planted.bundled).toEqual(["src/test-support/d.ts", "src/test-support/g.ts", "src/test-support/s.ts", "src/test-support/w.ts"]);
      expect(planted.productReach.has("src/globbed/g.ts"), "the glob edge was followed").toBe(true);
      expect(planted.testEdgesIntoSupport).toBe(1);

      /* A glob that reaches into the boundary is an edge like any other. */
      put("src/worker.ts", 'const m = import.meta.glob("./test-support/w.ts");\nexport { m };');
      expect(boundaryReport(moduleGraph(dir)).violations).toContain("src/worker.ts -> src/test-support/w.ts (import.meta.glob)");

      /* Comments are trivia to the bundler, and to this scan: each form written across one is still an edge. */
      put("src/commented.ts", 'export const c = () =>\n  import(\n    // lazily\n    "./test-support/d"\n  );\nexport const k = import(/* chunk: "g" */ "./test-support/g");');
      put("src/commented-from.ts", 'import { s } from /* golden */ "./test-support/s";\nexport { s };');
      const commented = boundaryReport(moduleGraph(dir)).violations;
      expect(commented).toContain("src/commented.ts -> src/test-support/d.ts (import)");
      expect(commented).toContain("src/commented.ts -> src/test-support/g.ts (import)");
      expect(commented).toContain("src/commented-from.ts -> src/test-support/s.ts (import)");
      rmSync(join(dir, "src", "commented.ts"));
      rmSync(join(dir, "src", "commented-from.ts"));

      /* A dynamic import Vite expands from pieces (concatenation, a template with substitutions) is read by
         its first literal piece: naming the boundary directory there is an edge into it. */
      put("src/concat.ts", 'export const a = (n: string) => import("./test-support/" + n + ".ts");');
      put("src/template.ts", "export const b = (n: string) => import(`./test-support/${n}.ts`);");
      const pieces = new Set(boundaryReport(moduleGraph(dir)).violations);
      expect(pieces).toContain("src/concat.ts -> src/test-support (import)");
      expect(pieces).toContain("src/template.ts -> src/test-support (import)");
      rmSync(join(dir, "src", "concat.ts"));
      rmSync(join(dir, "src", "template.ts"));

      /* A build configuration is a product entry: the default one and one a package script selects. Its
         inputs are plain strings, so a literal naming the boundary is an edge however it is joined. */
      put("package.json", '{"scripts": {"build": "tsc && vite build", "build:alt": "vite build --config build/alt.config.mjs"}}');
      put("vite.config.ts", 'import { resolve } from "node:path";\nexport default { build: { rollupOptions: { input: { t: resolve(__dirname, "src/test-support/s.ts") } } } };');
      put("build/alt.config.mjs", 'export default { build: { rollupOptions: { input: "./src/test-support/d.ts" } } };');
      const configured = moduleGraph(dir);
      expect(configured.entries).toEqual(expect.arrayContaining(["build/alt.config.mjs", "vite.config.ts"]));
      const viaConfig = boundaryReport(configured);
      expect(viaConfig.violations).toContain("vite.config.ts -> src/test-support/s.ts (build config)");
      expect(viaConfig.violations).toContain("build/alt.config.mjs -> src/test-support/d.ts (build config)");
      expect(viaConfig.bundled).toContain("src/test-support/s.ts");
      put("vite.config.ts", 'import { resolve } from "node:path";\nexport default { build: { rollupOptions: { input: { t: resolve(__dirname, "index.html") } } } };');
      put("build/alt.config.mjs", 'export default { build: { outDir: "dist-alt" } };');

      /* The same tree with every product edge into the boundary removed and the helper moved in is clean:
         a test importing test-support, and test-support importing product code, are both allowed. */
      put("src/static.ts", "export const x = 1;");
      put("src/dyn.ts", "export const f = 1;");
      put("src/globbed/g.ts", "export const g = 1;");
      put("src/worker.ts", "export const u = 1;");
      rmSync(join(dir, "src", "helper.ts"));
      put("src/test-support/helper.ts", "export const h = 1;");
      put("src/x.test.ts", 'import { h } from "./test-support/helper";\nimport { s } from "./test-support/s";\nexport { h, s };');
      const clean = boundaryReport(moduleGraph(dir));
      expect([clean.violations, clean.strays, clean.bundled]).toEqual([[], [], []]);
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });
});
